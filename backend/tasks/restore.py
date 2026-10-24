#!/usr/bin/env python3
"""
Data restore (database + material files)

Background: the backup module used to be write-only — the restore steps existed
only in comments and were never executed by any code. "A backup whose restore has
never been drilled equals no backup": format changes, wrong paths, manifest/files
mismatches and the like only surface when disaster actually strikes.

This module turns restore into executable, verifiable code:

1. verify_backup()     — check whether a backup is usable (files exist, archives
                         extract, the database opens, table counts match the manifest).
                         Touches no production data.
2. restore_database()  — restore the database from a backup. **Refuses to overwrite
                         an existing database by default**; requires an explicit --force
                         and automatically backs up the current database first.
3. restore_files()     — restore material files from the tar.gz, defaulting to a temp
                         directory for manual inspection.
4. drill()             — drill: restore a backup to a temporary location and verify the
                         data is readable, never touching the production database.
                         For periodically proving "the backup really restores".

Safety design (restore is destructive; prefer one extra confirmation)
- Restoring the database refuses to write to an existing database file by default;
  with --force the current database is first saved as .pre_restore.
- Archive integrity is verified before restoring; a corrupt backup is rejected outright,
  never leaving half a database behind.
- Path traversal protection: tar member paths are normalized and checked; ../ escapes are refused.
- After restoring, a data self-check runs automatically (critical table row counts, foreign key integrity).

Usage
    # Drill (safe; run regularly)
    python tasks/restore.py --drill

    # Verify a specific backup
    python tasks/restore.py --verify 20260920_030000

    # Actually restore the database (destructive, needs --force)
    python tasks/restore.py --restore-db 20260920_030000 --force

    # Restore material files to a temp directory for inspection
    python tasks/restore.py --restore-files 20260920_030000
"""
import argparse
import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile

logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Business-critical tables that must exist and be non-empty after a restore
CRITICAL_TABLES = ("users", "customers", "applications", "materials")

# Valid identifiers: SQLite table names may only contain alphanumerics and underscores
# \Z instead of $: in Python $ also matches "before a trailing newline", letting "users\n" pass
_IDENTIFIER_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _safe_ident(name: str) -> str:
    """Validate and return a table name safe for SQL.

    All table names here come from module constants and carry no injection risk by
    themselves; but making "safe" an assertion rather than a convention means that if
    someone later changes the names to come from config or user input, this blocks
    it outright instead of silently passing.
    """
    if not _IDENTIFIER_RE.match(name):
        raise RestoreError(f"非法表名，拒绝拼入 SQL: {name!r}")
    return name


class RestoreError(Exception):
    """Expected errors during restore (incomplete backup, unsupported format, etc.)"""


# ------------------------------------------------------------------ locate backup
def _backup_dir() -> str:
    from tasks.backup import get_backup_dir
    return get_backup_dir()


def find_backup(timestamp: str = None) -> dict:
    """Locate a backup and return its set of file paths.

    With timestamp empty, takes the latest one (manifests sorted by time, descending).

    Returns {"timestamp", "manifest", "db", "files", "manifest_data"}.
    Raises RestoreError when not found.
    """
    from tasks.backup import list_backups

    items = list_backups()
    if not items:
        raise RestoreError(f"备份目录中没有任何备份记录: {_backup_dir()}")

    if timestamp:
        match = next((i for i in items if i.get("timestamp") == timestamp), None)
        if match is None:
            available = [i.get("timestamp") for i in items[:10]]
            raise RestoreError(f"找不到时间戳为 {timestamp} 的备份。可用: {available}")
        item = match
    else:
        item = items[0]
        timestamp = item.get("timestamp")

    dest = _backup_dir()

    def _path(name):
        return os.path.join(dest, name) if name else None

    db_name = item.get("db_backup_file")
    files_name = item.get("files_backup_file")
    manifest_name = item.get("manifest_file")

    result = {
        "timestamp": timestamp,
        "manifest": _path(manifest_name),
        "db": _path(db_name),
        "files": _path(files_name),
        "manifest_data": item,
    }

    if not result["db"] or not os.path.exists(result["db"]):
        raise RestoreError(
            f"备份 {timestamp} 的数据库文件缺失: {db_name or '(manifest 未记录)'}"
        )
    return result


# ------------------------------------------------------------------ verification
def _verify_gzip(path: str) -> None:
    """Verify a gzip file extracts completely (only passing when EOF is reached)"""
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1024 * 1024):
                pass
    except Exception as e:
        raise RestoreError(f"gzip 文件损坏或不可解压 {os.path.basename(path)}: {e}") from e


def _verify_sqlite(path: str) -> dict:
    """Verify a SQLite backup opens with intact structure; returns {"tables": [...], "integrity": str}"""
    try:
        con = sqlite3.connect(path)
    except Exception as e:
        raise RestoreError(f"无法打开 SQLite 备份 {os.path.basename(path)}: {e}") from e

    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()
        integrity_msg = integrity[0] if integrity else "unknown"
        if integrity_msg != "ok":
            raise RestoreError(f"SQLite 完整性检查未通过: {integrity_msg}")
        tables = [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {"tables": tables, "integrity": integrity_msg}
    except RestoreError:
        raise
    except Exception as e:
        raise RestoreError(f"读取 SQLite 备份结构失败: {e}") from e
    finally:
        con.close()


def _verify_tar(path: str) -> dict:
    """Verify a tar.gz is readable; returns {"members": n}. Also checks path traversal."""
    count = 0
    try:
        with tarfile.open(path, "r:gz") as tar:
            for member in tar:
                # Path traversal protection: if extracted directly on restore, a malicious/corrupt archive could write outside the directory
                name = member.name.replace("\\", "/")
                normalized = os.path.normpath(name)
                if normalized.startswith("..") or os.path.isabs(normalized):
                    raise RestoreError(f"归档中存在非法路径（路径穿越）: {member.name}")
                if member.isfile():
                    count += 1
    except RestoreError:
        raise
    except Exception as e:
        raise RestoreError(f"tar 归档损坏或不可读 {os.path.basename(path)}: {e}") from e
    return {"members": count}


def verify_backup(timestamp: str = None, deep: bool = True) -> dict:
    """Verify whether a backup is usable for restore.

    With deep=True a full extraction check runs (slower but reliable); False only
    checks file existence and sizes. Returns the verification report dict; raises
    RestoreError on failure.
    """
    info = find_backup(timestamp)
    ts = info["timestamp"]
    report = {"timestamp": ts, "ok": False, "checks": [], "warnings": []}

    db_path = info["db"]
    db_size = os.path.getsize(db_path)
    report["db_file"] = os.path.basename(db_path)
    report["db_size_bytes"] = db_size

    if db_size == 0:
        raise RestoreError(f"数据库备份文件为空: {db_path}")
    report["checks"].append(f"数据库备份文件存在（{db_size} 字节）")

    # Extract to a temp directory, then verify the content
    with tempfile.TemporaryDirectory(prefix="trm_verify_") as tmp:
        if db_path.endswith(".gz"):
            if deep:
                _verify_gzip(db_path)
                report["checks"].append("gzip 可完整解压")
            extracted = os.path.join(tmp, "db.sqlite")
            with gzip.open(db_path, "rb") as fin, open(extracted, "wb") as fout:
                shutil.copyfileobj(fin, fout)
        else:
            extracted = db_path

        if extracted.endswith(".sqlite") or "sqlite" in os.path.basename(db_path):
            sqlite_info = _verify_sqlite(extracted)
            report["tables_count"] = len(sqlite_info["tables"])
            report["checks"].append(
                f"SQLite 完整性检查通过，共 {len(sqlite_info['tables'])} 张表"
            )

            missing = [t for t in CRITICAL_TABLES if t not in sqlite_info["tables"]]
            if missing:
                raise RestoreError(f"备份缺少关键业务表: {missing}")
            report["checks"].append(f"关键业务表齐全: {', '.join(CRITICAL_TABLES)}")

            # Compare against the table count recorded in the manifest (skipped when the manifest has none)
            manifest_tables = (info["manifest_data"] or {}).get("tables_count")
            if manifest_tables and manifest_tables != len(sqlite_info["tables"]):
                report["warnings"].append(
                    f"表数量与 manifest 记录不一致：manifest={manifest_tables}, "
                    f"实际={len(sqlite_info['tables'])}"
                )
        else:
            # PostgreSQL's .sql text backup: only a basic readability check
            report["warnings"].append("非 SQLite 备份，跳过结构校验（请用 psql 验证）")

    files_path = info["files"]
    if files_path:
        if not os.path.exists(files_path):
            raise RestoreError(f"manifest 记录了材料备份但文件缺失: {files_path}")
        report["files_file"] = os.path.basename(files_path)
        report["files_size_bytes"] = os.path.getsize(files_path)
        if deep:
            tar_info = _verify_tar(files_path)
            report["files_count"] = tar_info["members"]
            report["checks"].append(
                f"材料归档可读，共 {tar_info['members']} 个文件（路径检查通过）"
            )
        else:
            report["checks"].append("材料归档文件存在")

    report["ok"] = True
    return report


# ------------------------------------------------------------------ restore database
def restore_database(timestamp: str = None, force: bool = False,
                     target: str = None) -> dict:
    """Restore the database from a backup.

    Refuses to overwrite an existing database file by default (restore is destructive).
    With force=True the current database is first saved as <db file>.pre_restore_<timestamp>
    before writing.

    target specifies the database file to restore into; when empty, the database pointed
    to by the current DATABASE_URL is used. Returns the restore report dict.
    """
    info = find_backup(timestamp)
    ts = info["timestamp"]
    db_path = info["db"]

    if target:
        dest = os.path.abspath(target)
    else:
        from tasks.backup import _db_type, _sqlite_db_path
        if _db_type() != "sqlite":
            raise RestoreError(
                "当前数据库不是 SQLite，无法用文件替换方式恢复。"
                "请按 .env.example 的说明用 psql 导入 .sql 备份。"
            )
        dest = _sqlite_db_path()

    report = {"timestamp": ts, "target": dest, "ok": False, "steps": []}

    # Verify the backup is usable before restoring, so half a database is never written
    verification = verify_backup(ts)
    report["verification"] = verification
    report["steps"].append("备份校验通过")

    if os.path.exists(dest):
        if not force:
            raise RestoreError(
                f"目标库已存在: {dest}\n"
                "恢复会覆盖现有数据。确认无误后加 --force 重试"
                "（届时现有库会自动另存为 .pre_restore 备份）。"
            )
        safety = f"{dest}.pre_restore_{ts}"
        shutil.copy2(dest, safety)
        report["steps"].append(f"现有库已另存为 {os.path.basename(safety)}")
        report["safety_copy"] = safety

    # Extract/copy to the target location
    if db_path.endswith(".gz"):
        with gzip.open(db_path, "rb") as fin, open(dest, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        report["steps"].append("已从 gzip 解压写入目标库")
    else:
        shutil.copy2(db_path, dest)
        report["steps"].append("已复制备份文件到目标库")

    # Post-restore self-check: structure + critical table row counts
    sqlite_info = _verify_sqlite(dest)
    report["tables_count"] = len(sqlite_info["tables"])
    report["steps"].append(f"恢复后完整性检查通过，共 {len(sqlite_info['tables'])} 张表")

    report["row_counts"] = _row_counts(dest)
    report["steps"].append(f"关键表行数: {report['row_counts']}")

    fk_issues = _foreign_key_check(dest)
    if fk_issues:
        report["warnings"] = [f"外键引用异常 {len(fk_issues)} 处（前 5 条）: {fk_issues[:5]}"]
    else:
        report["steps"].append("外键完整性检查通过")

    report["ok"] = True
    return report


def _row_counts(db_path: str) -> dict:
    """Count rows in the critical tables (checking the data really came back after restore)"""
    counts = {}
    con = sqlite3.connect(db_path)
    try:
        for table in CRITICAL_TABLES:
            safe = _safe_ident(table)
            try:
                # Table names cannot be parameterized (SQL placeholders bind values, not identifiers),
                # so whitelist validation is used instead: safe has been confirmed by the _safe_ident regex.
                counts[safe] = con.execute(
                    f'SELECT COUNT(*) FROM "{safe}"'  # nosec B608
                ).fetchone()[0]
            except sqlite3.Error:
                counts[safe] = None
    finally:
        con.close()
    return counts


def _foreign_key_check(db_path: str) -> list:
    """Foreign key integrity check; returns violations (at most 20)"""
    issues = []
    con = sqlite3.connect(db_path)
    try:
        # PRAGMA foreign_key_check also runs on connections with foreign keys disabled
        for row in con.execute("PRAGMA foreign_key_check"):
            issues.append({"table": row[0], "rowid": row[1], "parent": row[2]})
            if len(issues) >= 20:
                break
    except sqlite3.Error as e:
        logger.warning(f"外键检查失败: {e}")
    finally:
        con.close()
    return issues


# ------------------------------------------------------------------ restore material files
def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, dest: str) -> None:
    """Extract a single member.

    From Python 3.12, tarfile.extract warns when no filter is given, and 3.14 will
    change the default; this project must support 3.10, so choose by version: use
    filter="data" when available (it has path traversal protection built in), else
    fall back to the default behavior with paths already validated manually.
    """
    try:
        tar.extract(member, path=dest, filter="data")
    except TypeError:
        # Python < 3.12 has no filter parameter; paths were normalized/validated by the caller
        tar.extract(member, path=dest)


def restore_files(timestamp: str = None, target: str = None) -> dict:
    """Restore material files.

    Without a target, extracts to a temp directory for manual inspection (never
    directly overwrites the production material directory — materials are customers'
    original documents, and accidental overwrite is costly).
    """
    info = find_backup(timestamp)
    ts = info["timestamp"]
    files_path = info["files"]
    if not files_path or not os.path.exists(files_path):
        raise RestoreError(f"备份 {ts} 不包含材料文件归档")

    dest = os.path.abspath(target) if target else tempfile.mkdtemp(
        prefix=f"trm_restore_files_{ts}_"
    )

    report = {"timestamp": ts, "target": dest, "ok": False, "steps": []}

    # Reuse the path traversal checks from verification
    tar_info = _verify_tar(files_path)
    report["steps"].append(f"归档校验通过，共 {tar_info['members']} 个文件")

    os.makedirs(dest, exist_ok=True)
    extracted = 0
    with tarfile.open(files_path, "r:gz") as tar:
        for member in tar:
            name = os.path.normpath(member.name.replace("\\", "/"))
            if name.startswith("..") or os.path.isabs(name):
                logger.warning(f"跳过非法路径成员: {member.name}")
                continue
            _extract_member(tar, member, dest)
            if member.isfile():
                extracted += 1

    report["extracted"] = extracted
    report["steps"].append(f"已解包 {extracted} 个文件到 {dest}")
    report["ok"] = True
    return report


# ------------------------------------------------------------------ drill
def drill(timestamp: str = None) -> dict:
    """Restore drill: run the full restore flow in a temporary location and verify the data is readable.

    Never touches the production database or the production material directory —
    this is the repeatable way to prove "the backup really works". Run it monthly,
    or after any change to the backup logic.
    """
    info = find_backup(timestamp)
    ts = info["timestamp"]
    report = {"timestamp": ts, "ok": False, "steps": [], "warnings": []}

    # 1) Verify
    verification = verify_backup(ts)
    report["verification"] = {
        "tables_count": verification.get("tables_count"),
        "files_count": verification.get("files_count"),
        "checks": verification["checks"],
    }
    report["steps"].append("备份校验通过")

    with tempfile.TemporaryDirectory(prefix="trm_drill_") as tmp:
        # 2) Restore the database to a temp file
        tmp_db = os.path.join(tmp, "restored.sqlite")
        db_report = restore_database(ts, force=True, target=tmp_db)
        report["steps"].append(f"数据库已恢复到临时位置，{db_report['tables_count']} 张表")
        report["row_counts"] = db_report.get("row_counts")
        report["warnings"].extend(db_report.get("warnings", []))

        # 3) Data readability check: run real queries against key business objects
        readable = _readability_check(tmp_db)
        report["readability"] = readable
        if readable["ok"]:
            report["steps"].append(
                f"数据可读：{readable['users']} 用户 / {readable['customers']} 客户 / "
                f"{readable['applications']} 批次"
            )
        else:
            report["warnings"].append(f"数据可读性检查异常: {readable.get('error')}")

        # 4) Restore material files to a temp directory
        if info["files"]:
            files_report = restore_files(ts, target=os.path.join(tmp, "files"))
            report["steps"].append(f"材料文件已恢复到临时位置，{files_report['extracted']} 个文件")

    report["ok"] = True
    return report


def _readability_check(db_path: str) -> dict:
    """Use real queries to prove the restored database works (not just openable — business data must be queryable)"""
    result = {"ok": False, "users": 0, "customers": 0, "applications": 0}
    con = sqlite3.connect(db_path)
    try:
        for key, table in (("users", "users"), ("customers", "customers"),
                           ("applications", "applications")):
            # Same as _row_counts: identifiers cannot be parameterized; whitelist-validate with _safe_ident
            result[key] = con.execute(
                f'SELECT COUNT(*) FROM "{_safe_ident(table)}"'  # nosec B608
            ).fetchone()[0]
        # Sample one customer record to confirm fields read correctly
        row = con.execute("SELECT id, name FROM customers LIMIT 1").fetchone()
        result["sample_customer"] = row[1] if row else None
        result["ok"] = True
    except sqlite3.Error as e:
        result["error"] = str(e)
    finally:
        con.close()
    return result


# ------------------------------------------------------------------ CLI
def _print_report(report: dict, title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"{title}")
    print("=" * 60)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print("=" * 60)
    print("结果:", "成功" if report.get("ok") else "失败")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="数据恢复与恢复演练")
    parser.add_argument("--list", action="store_true", help="列出可用备份")
    parser.add_argument("--verify", nargs="?", const="", metavar="TIMESTAMP",
                        help="校验备份（默认最新一份）")
    parser.add_argument("--drill", nargs="?", const="", metavar="TIMESTAMP",
                        help="恢复演练：恢复到临时位置并验证（安全，不碰生产数据）")
    parser.add_argument("--restore-db", nargs="?", const="", metavar="TIMESTAMP",
                        help="恢复数据库（破坏性）")
    parser.add_argument("--restore-files", nargs="?", const="", metavar="TIMESTAMP",
                        help="恢复材料文件（默认到临时目录）")
    parser.add_argument("--target", help="恢复目标路径")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的目标库（会先自动另存现有库）")
    args = parser.parse_args()

    try:
        if args.list:
            from tasks.backup import list_backups
            items = list_backups()
            if not items:
                print(f"备份目录中没有备份: {_backup_dir()}")
                return 1
            for item in items:
                flag = "成功" if item.get("success") else f"失败({item.get('error')})"
                print(f"  {item.get('timestamp')}  {flag}  "
                      f"db={item.get('db_backup_file')} files={item.get('files_backup_file')}")
            return 0

        if args.verify is not None:
            report = verify_backup(args.verify or None)
            _print_report(report, "备份校验")
            return 0

        if args.drill is not None:
            report = drill(args.drill or None)
            _print_report(report, "恢复演练（临时位置，未接触生产数据）")
            return 0

        if args.restore_db is not None:
            report = restore_database(args.restore_db or None, force=args.force,
                                      target=args.target)
            _print_report(report, "数据库恢复")
            return 0

        if args.restore_files is not None:
            report = restore_files(args.restore_files or None, target=args.target)
            _print_report(report, "材料文件恢复")
            return 0

        parser.print_help()
        return 0
    except RestoreError as e:
        print(f"\n恢复失败: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.exception("恢复过程异常")
        print(f"\n恢复过程异常: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
