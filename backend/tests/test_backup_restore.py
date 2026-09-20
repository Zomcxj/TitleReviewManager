"""备份与恢复测试。

核心目的：让「备份真的能恢复」成为可重复验证的事实，而不是注释里的步骤。

此前备份模块只写不读，恢复步骤仅存在于文档注释中，从未被任何代码执行过。
本文件覆盖：
- 备份产物完整性（db / files / manifest 三件套）
- 恢复校验（损坏备份必须被拒绝，不能写出半个库）
- 恢复演练（drill）全流程
- 恢复的破坏性保护（默认拒绝覆盖，force 时自动另存）
- 路径穿越防护
- 保留份数清理
- 备份失败告警

所有测试使用临时目录与临时数据库，绝不触碰开发库 title_service.db。
"""
import gzip
import json
import os
import sqlite3
import tarfile
from datetime import datetime, timedelta

import pytest

from tasks import backup as backup_task
from tasks import restore as restore_task
from tasks.restore import RestoreError


@pytest.fixture(name="backup_env")
def fixture_backup_env(tmp_path, monkeypatch):
    """搭建独立的备份环境：临时数据库 + 临时备份目录 + 临时材料目录

    注意：database.py 在 import 时就把 DATABASE_URL 固化为模块常量，因此
    monkeypatch.setenv 对它无效 —— 必须直接改模块属性，否则备份会打到开发库
    title_service.db（测试绝不能碰开发库）。
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
    monkeypatch.setattr("storage.get_storage_root", lambda: str(storage_root))

    # 建一个带业务数据的源库
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

    # 放两个材料文件
    (storage_root / "a.txt").write_text("material-a", encoding="utf-8")
    sub = storage_root / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("material-b", encoding="utf-8")

    # 前置断言：确认备份源确实是临时库而非开发库
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
    """备份产物完整性"""

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
    """恢复前校验：损坏的备份必须被拒绝"""

    def test_verify_healthy_backup(self, backup_env):
        _run_backup()
        report = restore_task.verify_backup()
        assert report["ok"] is True
        assert report["tables_count"] > 0
        assert report["files_count"] == 2

    def test_rejects_truncated_gzip(self, backup_env):
        result = _run_backup()
        # 截断 gzip 文件，模拟传输中断
        with open(result["db_backup"], "rb") as f:
            data = f.read()
        with open(result["db_backup"], "wb") as f:
            f.write(data[: len(data) // 2])

        with pytest.raises(RestoreError):
            restore_task.verify_backup()

    def test_rejects_empty_db_file(self, backup_env):
        result = _run_backup()
        with open(result["db_backup"], "wb"):
            pass  # 截断为 0 字节

        with pytest.raises(RestoreError, match="为空"):
            restore_task.verify_backup()

    def test_rejects_corrupt_sqlite(self, backup_env):
        """gzip 完好但内部不是合法 SQLite"""
        result = _run_backup()
        with gzip.open(result["db_backup"], "wb") as f:
            f.write(b"this is not a sqlite database at all")

        with pytest.raises(RestoreError):
            restore_task.verify_backup()

    def test_rejects_backup_with_missing_critical_table(self, backup_env):
        """关键业务表缺失的备份不可用于恢复"""
        result = _run_backup()
        # 重建一个删掉 users 表的库，再压缩回去
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
    """归档路径穿越防护"""

    def test_rejects_traversal_member(self, backup_env):
        _run_backup()
        result = backup_task.run_backup()

        # 构造含 ../ 的恶意归档替换材料归档
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
        # verify 会先拦下；这里直接验证解包逻辑本身也不写出目录
        with pytest.raises(RestoreError):
            restore_task.restore_files(target=str(target))

        assert not (backup_env["tmp_path"] / "escaped.txt").exists(), "文件逃逸出目标目录"


class TestDatabaseRestore:
    """数据库恢复的破坏性保护"""

    def test_refuses_to_overwrite_without_force(self, backup_env):
        _run_backup()
        with pytest.raises(RestoreError, match="已存在"):
            restore_task.restore_database(target=str(backup_env["db_path"]))

    def test_force_creates_safety_copy(self, backup_env):
        _run_backup()
        # 改掉现有库里的数据，确认恢复确实把它还原了
        con = sqlite3.connect(str(backup_env["db_path"]))
        con.execute("DELETE FROM users")
        con.commit()
        con.close()

        report = restore_task.restore_database(target=str(backup_env["db_path"]), force=True)
        assert report["ok"] is True
        assert "safety_copy" in report
        assert os.path.exists(report["safety_copy"]), "覆盖前必须另存现有库"

        # 数据回来了
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
        # 正常备份不应有外键问题
        assert not report.get("warnings"), f"意外告警: {report.get('warnings')}"


class TestRestoreDrill:
    """恢复演练：备份可用性的端到端证明"""

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
        """演练必须在临时位置进行，不碰生产库"""
        _run_backup()

        # 记下生产库的修改时间与内容指纹
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
        """演练不应在临时目录留下垃圾"""
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
    """保留份数清理"""

    def _seed_backups(self, backup_env, count: int) -> None:
        """直接构造 count 份备份三件套（不依赖 run_backup，避免同秒时间戳冲突）"""
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
        """清理时必须把 db/files/manifest 三件套一起删，不留孤儿"""
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
        """保留的必须是最新的几份"""
        self._seed_backups(backup_env, 4)
        backup_task._cleanup_old(str(backup_env["backup_dir"]), keep=2)

        stamps = sorted(
            n[len("manifest_"):-len(".json")]
            for n in os.listdir(backup_env["backup_dir"])
            if n.startswith("manifest_")
        )
        # 2026-01-01..04，应保留最后两个
        assert stamps == ["20260103_030000", "20260104_030000"], f"保留的不是最新份: {stamps}"

    def test_no_cleanup_when_under_limit(self, backup_env):
        self._seed_backups(backup_env, 2)
        deleted = backup_task._cleanup_old(str(backup_env["backup_dir"]), keep=5)
        assert deleted == []
        assert len([f for f in os.listdir(backup_env["backup_dir"])
                    if f.startswith("manifest_")]) == 2


class TestBackupFailureAlerting:
    """备份失败必须通知管理员（此前只写日志，等于静默失败）"""

    @pytest.fixture(name="admin_session")
    def fixture_admin_session(self, backup_env):
        """在临时库里建一个管理员，并把 database.SessionLocal 指向它"""
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
        """让数据库备份失败，但不破坏库文件（否则告警也写不进去）"""
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
            # fixture 里种了一个 admin 角色的 backupuser，预期数量需按实际查询
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
        """已删除的管理员不应收到告警"""
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
        """告警自身出错不能影响备份结果返回"""
        def boom(*a, **kw):
            raise RuntimeError("告警通道故障")

        monkeypatch.setattr(backup_task, "_notify_backup_failure", boom)
        self._make_db_backup_fail(monkeypatch)

        result = backup_task.run_backup(include_files=False)
        # 备份失败但函数正常返回结果（不抛异常）
        assert isinstance(result, dict)
        assert result["success"] is False


class TestSchedulerRestoreDrill:
    """调度器在备份成功后应自动做恢复演练"""

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
    """备份模块的健壮性"""

    def test_backup_failure_does_not_raise(self, backup_env, monkeypatch):
        """数据库备份失败时 run_backup 必须正常返回而非抛异常"""
        def boom(dest_dir, timestamp):
            raise RuntimeError("模拟备份失败")

        monkeypatch.setattr(backup_task, "_backup_sqlite", boom)
        result = backup_task.run_backup(include_files=False)
        assert result["success"] is False
        assert result["error"]

    def test_missing_db_file_is_reported(self, backup_env):
        """库文件真的不存在时也要正常返回错误而非抛异常"""
        os.remove(backup_env["db_path"])
        result = backup_task.run_backup(include_files=False)
        assert result["success"] is False
        assert result["error"]

    def test_manifest_written_even_on_failure(self, backup_env, monkeypatch):
        """失败也要写 manifest，便于判断「今天是否已备份」"""
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
    """表名白名单校验。

    恢复模块里有两处 `SELECT COUNT(*) FROM "{table}"`：SQL 占位符只能绑值、
    不能绑标识符，因此表名只能拼进语句。当前表名全部来自模块常量，没有注入
    风险；这组测试把「安全」变成可验证的约束 —— 一旦有人把表名改成来自配置
    或用户输入，非法名字会被直接拒绝，而不是静默拼进 SQL。
    """

    def test_accepts_normal_table_names(self):
        for name in ("users", "customers", "applications", "materials", "a1", "_x"):
            assert restore_task._safe_ident(name) == name

    @pytest.mark.parametrize("bad", [
        'users"; DROP TABLE customers; --',
        "users' OR '1'='1",
        "users; DROP TABLE users",
        "users--",
        "用户表",          # 非 ASCII
        "users table",     # 空格
        "",                # 空
        "1users",          # 数字开头
        "users)",          # 括号
        "users\n",         # 换行
    ])
    def test_rejects_dangerous_identifiers(self, bad):
        with pytest.raises(RestoreError):
            restore_task._safe_ident(bad)

    def test_critical_tables_are_valid(self):
        """常量表名必须全部通过校验（否则恢复流程会自己把自己拦下）"""
        for name in restore_task.CRITICAL_TABLES:
            assert restore_task._safe_ident(name) == name
