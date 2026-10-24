"""Backup and restore tests.

Core purpose: make "backups can actually be restored" a repeatably verifiable
fact, not a step list living in comments.

The backup module used to be write-only: restore steps existed only in doc
comments and were never executed by any code. This file covers:
- backup artifact integrity (db / files / manifest triplet)
- restore verification (corrupt backups must be rejected; half a database must never be written out)
- the full restore drill flow
- destructive-restore protection (overwrite refused by default; force auto-saves a safety copy)
- path traversal protection
- retention cleanup
- backup failure alerting
- offsite/off-disk copy push (BACKUP_SYNC_CMD hook)

All tests use temp directories and temp databases and never touch the dev
database title_service.db.
"""
import gzip
import json
import os
import sqlite3
import subprocess
import tarfile
import types
from datetime import datetime, timedelta

import pytest

from tasks import backup as backup_task
from tasks import restore as restore_task
from tasks.restore import RestoreError


@pytest.fixture(name="backup_env")
def fixture_backup_env(tmp_path, monkeypatch):
    """Set up an isolated backup environment: temp database + temp backup dir + temp materials dir

    Note: database.py freezes DATABASE_URL into a module constant at import time,
    so monkeypatch.setenv has no effect on it — the module attribute must be
    patched directly, otherwise backups would hit the dev database
    title_service.db (tests must never touch the dev database).
    """
    db_path = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr("database.DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("BACKUP_KEEP", "3")
    monkeypatch.setenv("BACKUP_COMPRESS", "1")
    monkeypatch.setenv("BACKUP_INCLUDE_FILES", "1")
    monkeypatch.setenv("BACKUP_ENABLED", "1")
    # The sync hook must be explicitly enabled per test as needed: if a developer's
    # local .env configures it, every "off by default" assertion would break
    monkeypatch.delenv("BACKUP_SYNC_CMD", raising=False)
    monkeypatch.setattr("storage.get_storage_root", lambda: str(storage_root))

    # Create a source database with business data
    from sqlalchemy import create_engine

    import models  # noqa: F401
    from database import Base

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO users (username, password_hash, role, is_deleted, token_version, "
        "must_change_password, created_at) VALUES (?,?,?,?,?,?,?)",
        ("backupuser", "hash", "admin", 0, 0, 0, "2026-01-01 00:00:00"),
    )
    con.execute(
        "INSERT INTO customers (name, id_number, phone, is_deleted, is_public, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("测试客户", "110101199001011234", "13800000000", 0, 0, "2026-01-01 00:00:00"),
    )
    con.commit()
    con.close()
    engine.dispose()

    # Place two material files
    (storage_root / "a.txt").write_text("material-a", encoding="utf-8")
    sub = storage_root / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("material-b", encoding="utf-8")

    # Precondition assertion: confirm the backup source really is the temp database, not the dev one
    assert backup_task._sqlite_db_path() == os.path.abspath(str(db_path)), (
        "备份源不是临时库 —— 测试会打到开发库，必须修正"
    )

    return {
        "db_path": db_path,
        "backup_dir": backup_dir,
        "storage_root": storage_root,
        "tmp_path": tmp_path,
    }


def _run_backup(include_files=True):
    return backup_task.run_backup(include_files=include_files)


class TestBackupArtifacts:
    """Backup artifact integrity"""

    def test_creates_db_files_manifest(self, backup_env):
        result = _run_backup()
        assert result["success"] is True, f"备份失败: {result['error']}"

        assert result["db_backup"] and os.path.exists(result["db_backup"])
        assert result["files_backup"] and os.path.exists(result["files_backup"])
        assert result["manifest"] and os.path.exists(result["manifest"])

    def test_manifest_records_row_level_facts(self, backup_env):
        result = _run_backup()
        with open(result["manifest"], encoding="utf-8") as f:
            manifest = json.load(f)

        assert manifest["success"] is True
        assert manifest["db_type"] == "sqlite"
        assert manifest["db_file_size_bytes"] > 0
        assert manifest["files_count"] == 2
        assert manifest["error"] is None

    def test_files_archive_contains_materials(self, backup_env):
        result = _run_backup()
        with tarfile.open(result["files_backup"], "r:gz") as tar:
            names = {m.name for m in tar.getmembers() if m.isfile()}
        assert names == {"a.txt", "sub/b.txt"}, f"归档内容不符: {names}"


class TestBackupVerification:
    """Pre-restore verification: corrupt backups must be rejected"""

    def test_verify_healthy_backup(self, backup_env):
        _run_backup()
        report = restore_task.verify_backup()
        assert report["ok"] is True
        assert report["tables_count"] > 0
        assert report["files_count"] == 2

    def test_rejects_truncated_gzip(self, backup_env):
        result = _run_backup()
        # Truncate the gzip file to simulate a transfer interruption
        with open(result["db_backup"], "rb") as f:
            data = f.read()
        with open(result["db_backup"], "wb") as f:
            f.write(data[: len(data) // 2])

        with pytest.raises(RestoreError):
            restore_task.verify_backup()

    def test_rejects_empty_db_file(self, backup_env):
        result = _run_backup()
        with open(result["db_backup"], "wb"):
            pass  # Truncate to 0 bytes

        with pytest.raises(RestoreError, match="为空"):
            restore_task.verify_backup()

    def test_rejects_corrupt_sqlite(self, backup_env):
        """gzip intact but the contents are not a valid SQLite database"""
        result = _run_backup()
        with gzip.open(result["db_backup"], "wb") as f:
            f.write(b"this is not a sqlite database at all")

        with pytest.raises(RestoreError):
            restore_task.verify_backup()

    def test_rejects_backup_with_missing_critical_table(self, backup_env):
        """A backup missing critical business tables must not be usable for restore"""
        result = _run_backup()
        # Rebuild a database with the users table dropped, then compress it back
        tmp = backup_env["tmp_path"] / "no_users.sqlite"
        con = sqlite3.connect(str(backup_env["db_path"]))
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("DROP TABLE users")
        con.commit()
        con.close()

        import shutil
        shutil.copy2(backup_env["db_path"], tmp)
        with open(tmp, "rb") as fin, gzip.open(result["db_backup"], "wb") as fout:
            shutil.copyfileobj(fin, fout)

        with pytest.raises(RestoreError, match="关键业务表"):
            restore_task.verify_backup()

    def test_rejects_unknown_timestamp(self, backup_env):
        _run_backup()
        with pytest.raises(RestoreError, match="找不到"):
            restore_task.verify_backup("19990101_000000")

    def test_rejects_when_no_backup_exists(self, backup_env):
        with pytest.raises(RestoreError, match="没有任何备份"):
            restore_task.verify_backup()


class TestPathTraversalProtection:
    """Archive path traversal protection"""

    def test_rejects_traversal_member(self, backup_env):
        _run_backup()
        result = backup_task.run_backup()

        # Build a malicious archive containing ../ to replace the materials archive
        evil = backup_env["tmp_path"] / "evil.tar.gz"
        payload = backup_env["tmp_path"] / "payload.txt"
        payload.write_text("pwned", encoding="utf-8")
        with tarfile.open(evil, "w:gz") as tar:
            tar.add(payload, arcname="../../escaped.txt")

        import shutil
        shutil.copy2(evil, result["files_backup"])

        with pytest.raises(RestoreError, match="非法路径|路径穿越"):
            restore_task.verify_backup()

    def test_restore_files_skips_traversal(self, backup_env):
        result = _run_backup()
        evil = backup_env["tmp_path"] / "evil2.tar.gz"
        payload = backup_env["tmp_path"] / "payload2.txt"
        payload.write_text("pwned", encoding="utf-8")
        with tarfile.open(evil, "w:gz") as tar:
            tar.add(payload, arcname="../escaped.txt")
            tar.add(payload, arcname="safe.txt")

        import shutil
        shutil.copy2(evil, result["files_backup"])

        target = backup_env["tmp_path"] / "restored"
        # verify catches this first; here we verify the unpacking logic itself
        # never writes outside the target directory
        with pytest.raises(RestoreError):
            restore_task.restore_files(target=str(target))

        assert not (backup_env["tmp_path"] / "escaped.txt").exists(), "文件逃逸出目标目录"


class TestDatabaseRestore:
    """Destructive-restore protection for database recovery"""

    def test_refuses_to_overwrite_without_force(self, backup_env):
        _run_backup()
        with pytest.raises(RestoreError, match="已存在"):
            restore_task.restore_database(target=str(backup_env["db_path"]))

    def test_force_creates_safety_copy(self, backup_env):
        _run_backup()
        # Modify data in the existing database, then confirm restore actually reverts it
        con = sqlite3.connect(str(backup_env["db_path"]))
        con.execute("DELETE FROM users")
        con.commit()
        con.close()

        report = restore_task.restore_database(target=str(backup_env["db_path"]), force=True)
        assert report["ok"] is True
        assert "safety_copy" in report
        assert os.path.exists(report["safety_copy"]), "覆盖前必须另存现有库"

        # Data is back
        con = sqlite3.connect(str(backup_env["db_path"]))
        count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        con.close()
        assert count == 1, "恢复后应找回原有数据"

    def test_restore_to_fresh_target(self, backup_env):
        _run_backup()
        target = backup_env["tmp_path"] / "restored.db"
        report = restore_task.restore_database(target=str(target))

        assert report["ok"] is True
        assert target.exists()
        assert report["row_counts"]["users"] == 1
        assert report["row_counts"]["customers"] == 1

    def test_restore_reports_foreign_key_issues(self, backup_env):
        _run_backup()
        target = backup_env["tmp_path"] / "fk.db"
        report = restore_task.restore_database(target=str(target))
        # A normal backup should have no foreign key issues
        assert not report.get("warnings"), f"意外告警: {report.get('warnings')}"


class TestRestoreDrill:
    """Restore drill: end-to-end proof of backup usability"""

    def test_drill_succeeds_end_to_end(self, backup_env):
        _run_backup()
        report = restore_task.drill()

        assert report["ok"] is True, f"演练失败: {report}"
        assert report["verification"]["tables_count"] > 0
        assert report["verification"]["files_count"] == 2
        assert report["readability"]["ok"] is True
        assert report["readability"]["users"] == 1
        assert report["readability"]["customers"] == 1
        assert report["readability"]["sample_customer"] == "测试客户"

    def test_drill_does_not_touch_production_db(self, backup_env):
        """The drill must run in a temp location and never touch the production database"""
        _run_backup()

        # Record the production database's mtime and content fingerprint
        before_mtime = os.path.getmtime(backup_env["db_path"])
        con = sqlite3.connect(str(backup_env["db_path"]))
        before = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        con.close()

        restore_task.drill()

        after_mtime = os.path.getmtime(backup_env["db_path"])
        con = sqlite3.connect(str(backup_env["db_path"]))
        after = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        con.close()

        assert before == after
        assert before_mtime == after_mtime, "演练改动了生产库文件"

    def test_drill_cleans_up_temp_dir(self, backup_env):
        """The drill must not leave junk behind in the temp directory"""
        import tempfile
        _run_backup()
        tmp_root = tempfile.gettempdir()
        before = {d for d in os.listdir(tmp_root) if d.startswith("trm_drill_")}

        restore_task.drill()

        after = {d for d in os.listdir(tmp_root) if d.startswith("trm_drill_")}
        assert after == before, f"演练残留临时目录: {after - before}"

    def test_drill_rejects_corrupt_backup(self, backup_env):
        result = _run_backup()
        with open(result["db_backup"], "wb"):
            pass
        with pytest.raises(RestoreError):
            restore_task.drill()


class TestRetentionCleanup:
    """Retention cleanup"""

    def _seed_backups(self, backup_env, count: int) -> None:
        """Directly construct count backup triplets (without run_backup, to avoid same-second timestamp collisions)"""
        backup_dir = backup_env["backup_dir"]
        backup_dir.mkdir(parents=True, exist_ok=True)

        base = datetime(2026, 1, 1, 3, 0, 0)
        for i in range(count):
            ts = (base + timedelta(days=i)).strftime(backup_task.TIMESTAMP_FORMAT)
            (backup_dir / f"db_{ts}.sqlite.gz").write_bytes(b"fake-db")
            (backup_dir / f"files_{ts}.tar.gz").write_bytes(b"fake-files")
            (backup_dir / f"manifest_{ts}.json").write_text(
                json.dumps({
                    "timestamp": ts,
                    "backup_time": (base + timedelta(days=i)).isoformat(),
                    "success": True,
                    "db_backup_file": f"db_{ts}.sqlite.gz",
                    "files_backup_file": f"files_{ts}.tar.gz",
                }, ensure_ascii=False),
                encoding="utf-8",
            )

    def test_keeps_configured_count(self, backup_env):
        self._seed_backups(backup_env, 5)
        deleted = backup_task._cleanup_old(str(backup_env["backup_dir"]), keep=3)

        remaining = [f for f in os.listdir(backup_env["backup_dir"])
                     if f.startswith("manifest_")]
        assert len(remaining) == 3, f"应保留 3 份，实际 {len(remaining)}"
        assert len(deleted) == 6, f"应删除 2 份 × 3 个文件 = 6 个，实际 {len(deleted)}"

    def test_cleanup_removes_matching_triplets(self, backup_env):
        """Cleanup must delete the db/files/manifest triplet together, leaving no orphans"""
        self._seed_backups(backup_env, 5)
        backup_task._cleanup_old(str(backup_env["backup_dir"]), keep=2)

        names = os.listdir(backup_env["backup_dir"])
        db_stamps = {n[len("db_"):-len(".sqlite.gz")] for n in names if n.startswith("db_")}
        files_stamps = {n[len("files_"):-len(".tar.gz")] for n in names if n.startswith("files_")}
        manifest_stamps = {
            n[len("manifest_"):-len(".json")] for n in names if n.startswith("manifest_")
        }

        assert db_stamps == files_stamps == manifest_stamps, (
            f"三件套不匹配，存在孤儿文件: db={db_stamps} files={files_stamps} "
            f"manifest={manifest_stamps}"
        )
        assert len(db_stamps) == 2

    def test_keeps_newest(self, backup_env):
        """The kept ones must be the newest"""
        self._seed_backups(backup_env, 4)
        backup_task._cleanup_old(str(backup_env["backup_dir"]), keep=2)

        stamps = sorted(
            n[len("manifest_"):-len(".json")]
            for n in os.listdir(backup_env["backup_dir"])
            if n.startswith("manifest_")
        )
        # 2026-01-01..04; the last two should be kept
        assert stamps == ["20260103_030000", "20260104_030000"], f"保留的不是最新份: {stamps}"

    def test_no_cleanup_when_under_limit(self, backup_env):
        self._seed_backups(backup_env, 2)
        deleted = backup_task._cleanup_old(str(backup_env["backup_dir"]), keep=5)
        assert deleted == []
        assert len([f for f in os.listdir(backup_env["backup_dir"])
                    if f.startswith("manifest_")]) == 2


class TestBackupFailureAlerting:
    """Backup failures must notify admins (previously log-only, i.e. silent failure)"""

    @pytest.fixture(name="admin_session")
    def fixture_admin_session(self, backup_env):
        """Create an admin in the temp database and point database.SessionLocal at it"""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import models

        engine = create_engine(f"sqlite:///{backup_env['db_path']}")
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            admin = models.User(
                username="alertadmin", password_hash="x", role="admin",
                is_deleted=False, token_version=0, must_change_password=False,
            )
            db.add(admin)
            db.commit()
            admin_id = admin.id
        finally:
            db.close()
        engine.dispose()

        return {"Session": Session, "admin_id": admin_id, "db_path": backup_env["db_path"]}

    def _make_db_backup_fail(self, monkeypatch):
        """Make the database backup fail without corrupting the db file (otherwise the alert could not be written either)"""
        def boom(dest_dir, timestamp):
            raise RuntimeError("模拟磁盘写入失败")

        monkeypatch.setattr(backup_task, "_backup_sqlite", boom)

    def test_notification_created_on_failure(self, backup_env, admin_session, monkeypatch):
        monkeypatch.setattr("database.SessionLocal", admin_session["Session"])
        self._make_db_backup_fail(monkeypatch)

        result = backup_task.run_backup(include_files=False)
        assert result["success"] is False, "预期备份失败但成功了"

        import models
        db = admin_session["Session"]()
        try:
            notes = db.query(models.Notification).filter(
                models.Notification.user_id == admin_session["admin_id"],
                models.Notification.type == "backup_failed",
            ).all()
        finally:
            db.close()

        assert notes, "备份失败未创建通知"
        assert "模拟磁盘写入失败" in notes[0].content, "通知应带上失败原因"

    def test_notifies_all_admins(self, backup_env, admin_session, monkeypatch):
        import models
        db = admin_session["Session"]()
        try:
            second = models.User(
                username="admin2", password_hash="x", role="admin",
                is_deleted=False, token_version=0, must_change_password=False,
            )
            db.add(second)
            db.commit()
            # The fixture seeds a backupuser with the admin role; the expected count must be queried for real
            expected = db.query(models.User).filter(
                models.User.role == "admin", models.User.is_deleted == False  # noqa: E712
            ).count()
        finally:
            db.close()
        assert expected >= 2

        monkeypatch.setattr("database.SessionLocal", admin_session["Session"])
        self._make_db_backup_fail(monkeypatch)
        backup_task.run_backup(include_files=False)

        db = admin_session["Session"]()
        try:
            count = db.query(models.Notification).filter(
                models.Notification.type == "backup_failed"
            ).count()
        finally:
            db.close()

        assert count == expected, f"应通知全部 {expected} 位管理员，实际 {count} 条"

    def test_skips_deleted_admins(self, backup_env, admin_session, monkeypatch):
        """Deleted admins must not receive alerts"""
        import models
        db = admin_session["Session"]()
        try:
            ghost = models.User(
                username="ghostadmin", password_hash="x", role="admin",
                is_deleted=True, token_version=0, must_change_password=False,
            )
            db.add(ghost)
            db.commit()
            active = db.query(models.User).filter(
                models.User.role == "admin", models.User.is_deleted == False  # noqa: E712
            ).count()
        finally:
            db.close()

        monkeypatch.setattr("database.SessionLocal", admin_session["Session"])
        self._make_db_backup_fail(monkeypatch)
        backup_task.run_backup(include_files=False)

        db = admin_session["Session"]()
        try:
            count = db.query(models.Notification).filter(
                models.Notification.type == "backup_failed"
            ).count()
        finally:
            db.close()

        assert count == active, "已删除的管理员不应收到告警"

    def test_no_alert_on_success(self, backup_env, admin_session, monkeypatch):
        monkeypatch.setattr("database.SessionLocal", admin_session["Session"])
        result = backup_task.run_backup(include_files=False)
        assert result["success"] is True

        import models
        db = admin_session["Session"]()
        try:
            count = db.query(models.Notification).filter(
                models.Notification.type == "backup_failed"
            ).count()
        finally:
            db.close()

        assert count == 0, "成功备份不应产生失败告警"

    def test_alert_failure_does_not_break_backup_result(self, backup_env, monkeypatch):
        """An error in alerting itself must not affect the backup result"""
        def boom(*a, **kw):
            raise RuntimeError("告警通道故障")

        monkeypatch.setattr(backup_task, "_notify_backup_failure", boom)
        self._make_db_backup_fail(monkeypatch)

        result = backup_task.run_backup(include_files=False)
        # Backup failed but the function returns the result normally (no exception)
        assert isinstance(result, dict)
        assert result["success"] is False


class TestSchedulerRestoreDrill:
    """The scheduler should automatically run a restore drill after a successful backup"""

    def test_drill_called_after_successful_backup(self, backup_env, monkeypatch):
        from utils import scheduler

        called = {"n": 0}

        def fake_drill(timestamp=None):
            called["n"] += 1
            return {"ok": True, "row_counts": {"users": 1}}

        monkeypatch.setattr("tasks.restore.drill", fake_drill)
        result = {"warnings": []}
        scheduler._maybe_run_restore_drill(result)

        assert called["n"] == 1, "备份成功后应触发恢复演练"
        assert result["restore_drill"]["ok"] is True
        assert not result["warnings"]

    def test_drill_failure_becomes_warning(self, monkeypatch):
        from utils import scheduler

        def boom(timestamp=None):
            raise RuntimeError("演练环境不可用")

        monkeypatch.setattr("tasks.restore.drill", boom)
        result = {"warnings": []}
        scheduler._maybe_run_restore_drill(result)

        assert result["warnings"], "演练失败必须显式告警（备份可用性存疑）"
        assert "恢复演练失败" in result["warnings"][0]

    def test_drill_can_be_disabled(self, monkeypatch):
        from utils import scheduler

        called = {"n": 0}
        monkeypatch.setattr("tasks.restore.drill",
                            lambda timestamp=None: called.__setitem__("n", called["n"] + 1))
        monkeypatch.setenv("BACKUP_DRILL_ENABLED", "0")

        result = {"warnings": []}
        scheduler._maybe_run_restore_drill(result)

        assert called["n"] == 0, "BACKUP_DRILL_ENABLED=0 时不应执行演练"


class TestBackupModuleRobustness:
    """Backup module robustness"""

    def test_backup_failure_does_not_raise(self, backup_env, monkeypatch):
        """run_backup must return normally instead of raising when the database backup fails"""
        def boom(dest_dir, timestamp):
            raise RuntimeError("模拟备份失败")

        monkeypatch.setattr(backup_task, "_backup_sqlite", boom)
        result = backup_task.run_backup(include_files=False)
        assert result["success"] is False
        assert result["error"]

    def test_missing_db_file_is_reported(self, backup_env):
        """A genuinely missing db file must also return an error normally instead of raising"""
        os.remove(backup_env["db_path"])
        result = backup_task.run_backup(include_files=False)
        assert result["success"] is False
        assert result["error"]

    def test_manifest_written_even_on_failure(self, backup_env, monkeypatch):
        """Write the manifest even on failure, so "has today's backup run" can be determined"""
        def boom(dest_dir, timestamp):
            raise RuntimeError("模拟备份失败")

        monkeypatch.setattr(backup_task, "_backup_sqlite", boom)
        result = backup_task.run_backup(include_files=False)
        assert result["manifest"] and os.path.exists(result["manifest"])

        with open(result["manifest"], encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["success"] is False
        assert manifest["error"]

    def test_skips_files_when_disabled(self, backup_env):
        result = backup_task.run_backup(include_files=False)
        assert result["success"] is True
        assert result["files_backup"] is None


class TestTableNameValidation:
    """Table name whitelist validation.

    The restore module has two `SELECT COUNT(*) FROM "{table}"` spots: SQL
    placeholders can only bind values, not identifiers, so table names must be
    spliced into the statement. Table names currently all come from module
    constants and carry no injection risk; these tests turn "safe" into a
    verifiable constraint — if anyone changes table names to come from config
    or user input, invalid names get rejected outright instead of being
    silently spliced into SQL.
    """

    def test_accepts_normal_table_names(self):
        for name in ("users", "customers", "applications", "materials", "a1", "_x"):
            assert restore_task._safe_ident(name) == name

    @pytest.mark.parametrize("bad", [
        'users"; DROP TABLE customers; --',
        "users' OR '1'='1",
        "users; DROP TABLE users",
        "users--",
        "用户表",          # non-ASCII
        "users table",     # whitespace
        "",                # empty
        "1users",          # starts with a digit
        "users)",          # parenthesis
        "users\n",         # newline
    ])
    def test_rejects_dangerous_identifiers(self, bad):
        with pytest.raises(RestoreError):
            restore_task._safe_ident(bad)

    def test_critical_tables_are_valid(self):
        """Constant table names must all pass validation (otherwise the restore flow would block itself)"""
        for name in restore_task.CRITICAL_TABLES:
            assert restore_task._safe_ident(name) == name


class TestOffsiteSync:
    """Offsite/off-disk copy push (BACKUP_SYNC_CMD hook).

    Background: the backup directory and the database live on the same host by
    default, so host failure loses both. The hook pushes a copy to an arbitrary
    target after each successful backup; all of its contracts are verified here:
    off by default, placeholder replacement, failure never overturns backup
    success, failure must alert, and it never raises.
    """

    @staticmethod
    def _fake_subprocess(monkeypatch, returncode=0, stderr="", exc=None):
        """Subprocess stand-in: records the commands it receives, returns a canned result or raises a canned exception."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if exc is not None:
                raise exc
            return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

        monkeypatch.setattr(
            backup_task, "subprocess",
            types.SimpleNamespace(run=fake_run, TimeoutExpired=subprocess.TimeoutExpired),
        )
        return calls

    @staticmethod
    def _captured_alerts(monkeypatch):
        alerts = []
        monkeypatch.setattr(
            backup_task, "_notify_admins",
            lambda title, content: alerts.append((title, content)),
        )
        return alerts

    def test_disabled_by_default_never_spawns_process(self, backup_env, monkeypatch):
        """With no BACKUP_SYNC_CMD configured there must be zero overhead: not a single process may be spawned."""
        calls = self._fake_subprocess(
            monkeypatch,
            exc=AssertionError("未配置同步命令时不应调用 subprocess"),
        )
        result = _run_backup()
        assert result["success"] is True
        assert result["offsite_sync"] is None
        assert calls == []

    def test_placeholder_replaced_with_backup_dir(self, backup_env, monkeypatch):
        cmd_tpl = "rsync -a {backup_dir}/ /mnt/disk2/"
        monkeypatch.setenv("BACKUP_SYNC_CMD", cmd_tpl)
        calls = self._fake_subprocess(monkeypatch)
        result = _run_backup()

        assert result["success"] is True
        assert len(calls) == 1
        assert "{backup_dir}" not in calls[0], "占位符必须被替换"
        assert str(backup_env["backup_dir"]) in calls[0]

    def test_success_recorded_without_alert(self, backup_env, monkeypatch):
        monkeypatch.setenv("BACKUP_SYNC_CMD", "true")
        self._fake_subprocess(monkeypatch, returncode=0)
        alerts = self._captured_alerts(monkeypatch)
        result = _run_backup()

        assert result["success"] is True
        assert result["offsite_sync"]["ok"] is True
        assert "duration_seconds" in result["offsite_sync"]
        assert alerts == [], "同步成功不应触发任何告警"

    def test_failure_keeps_backup_success_and_alerts(self, backup_env, monkeypatch):
        """The local backup succeeded; a failed copy push only degrades to an alert and must not overturn the backup itself."""
        monkeypatch.setenv("BACKUP_SYNC_CMD", "rsync -a {backup_dir}/ nosuchhost:/x/")
        self._fake_subprocess(monkeypatch, returncode=23, stderr="rsync: connection refused")
        alerts = self._captured_alerts(monkeypatch)
        result = _run_backup()

        assert result["success"] is True, "同步失败不能推翻本地备份的成功"
        assert result["offsite_sync"]["ok"] is False
        assert result["offsite_sync"]["returncode"] == 23
        assert "connection refused" in result["offsite_sync"]["error"]
        assert len(alerts) == 1
        title, content = alerts[0]
        assert title == "备份副本同步失败"
        assert "connection refused" in content

    def test_timeout_alerts_and_keeps_backup_success(self, backup_env, monkeypatch):
        monkeypatch.setenv("BACKUP_SYNC_CMD", "rclone copy {backup_dir} remote:x")
        self._fake_subprocess(
            monkeypatch,
            exc=subprocess.TimeoutExpired(cmd="rclone", timeout=600),
        )
        alerts = self._captured_alerts(monkeypatch)
        result = _run_backup()

        assert result["success"] is True
        assert result["offsite_sync"]["ok"] is False
        assert "600" in result["offsite_sync"]["error"]
        assert len(alerts) == 1

    def test_hook_exception_never_breaks_backup(self, backup_env, monkeypatch):
        """run_backup's "never raises" contract holds for the sync channel too."""
        monkeypatch.setenv("BACKUP_SYNC_CMD", "whatever")

        def boom(*a, **k):
            raise RuntimeError("同步通道内部炸了")

        monkeypatch.setattr(backup_task, "_run_offsite_sync", boom)
        result = _run_backup()

        assert result["success"] is True
        assert result["offsite_sync"]["ok"] is False
        assert "同步通道内部炸了" in result["offsite_sync"]["error"]

    def test_failed_backup_does_not_trigger_sync(self, backup_env, monkeypatch):
        """Do not push an incomplete copy when the backup failed — pushing a bad backup is more dangerous than not pushing."""
        monkeypatch.setenv("BACKUP_SYNC_CMD", "true")
        # Make the database backup stage fail: DATABASE_URL points at a nonexistent
        # directory, so connect is guaranteed to error. backup.py's _db_url() only
        # does `from database import DATABASE_URL` at call time, so patching the
        # database module attribute takes effect (same technique as the backup_env fixture).
        monkeypatch.setattr(
            "database.DATABASE_URL",
            f"sqlite:///{backup_env['tmp_path']}/nonexistent_dir/x.db",
        )
        calls = self._fake_subprocess(monkeypatch)
        result = _run_backup()

        assert result["success"] is False
        assert calls == [], "失败的备份不应触发副本推送"
