#!/usr/bin/env python3
"""
数据恢复（数据库 + 材料文件）

背景：备份模块此前只写不读 —— 恢复步骤仅存在于注释中，从未被任何代码执行过。
「从没演练过恢复的备份等于没有备份」：格式变化、路径写错、manifest 与实际文件
不一致等问题，都要等到真出事时才会暴露。

本模块把恢复变成可执行、可校验的代码：

1. verify_backup()  —— 校验一份备份是否可用（文件存在、可解压、库可打开、
                      表数量与 manifest 记录一致）。不碰任何生产数据。
2. restore_database() —— 从备份恢复数据库。**默认拒绝覆盖现有库**，
                      必须显式指定 --force 且自动先备份当前库。
3. restore_files()  —— 从 tar.gz 恢复材料文件，默认恢复到临时目录供人工核对。
4. drill()          —— 演练：把备份恢复到一个临时位置并校验数据可读，
                      全过程不接触生产库。用于定期验证「备份真的能恢复」。

安全设计（恢复是破坏性操作，宁可多一道确认）
- 恢复数据库默认拒绝写入已存在的库文件；--force 时先把现有库另存为 .pre_restore。
- 恢复前校验归档完整性，损坏的备份直接拒绝，不会写出半个库。
- 路径穿越防护：tar 成员路径做归一化检查，拒绝 ../ 逃逸。
- 恢复后自动做一次数据自检（关键表行数、外键完整性）。

用法
    # 演练（安全，推荐定期执行）
    python tasks/restore.py --drill

    # 校验某份备份
    python tasks/restore.py --verify 20260920_030000

    # 真正恢复数据库（破坏性，需 --force）
    python tasks/restore.py --restore-db 20260920_030000 --force

    # 恢复材料文件到临时目录核对
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

# 恢复后必须存在且非空的业务关键表
CRITICAL_TABLES = ("users", "customers", "applications", "materials")

# 合法标识符：SQLite 表名只能由字母数字下划线组成
# 用 \Z 而非 $：$ 在 Python 里也匹配「结尾换行之前」，会让 "users\n" 通过校验
_IDENTIFIER_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _safe_ident(name: str) -> str:
    """校验并返回可用于 SQL 的表名。

    这里的表名全部来自模块常量，本身没有注入风险；但把「安全」写成断言而非
    约定，日后若有人把表名改成来自配置或用户输入，这里会直接拦下而不是静默放行。
    """
    if not _IDENTIFIER_RE.match(name):
        raise RestoreError(f"非法表名，拒绝拼入 SQL: {name!r}")
    return name


class RestoreError(Exception):
    """恢复过程中的可预期错误（不完整备份、格式不支持等）"""


# ------------------------------------------------------------------ 定位备份
def _backup_dir() -> str:
    from tasks.backup import get_backup_dir
    return get_backup_dir()


def find_backup(timestamp: str = None) -> dict:
    """定位一份备份，返回其文件路径集合。

    timestamp 为空时取最新一份（按 manifest 时间倒序）。

    返回 {"timestamp", "manifest", "db", "files", "manifest_data"}
    找不到时抛 RestoreError。
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


# ------------------------------------------------------------------ 校验
def _verify_gzip(path: str) -> None:
    """校验 gzip 文件可完整解压（读到 EOF 才算通过）"""
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1024 * 1024):
                pass
    except Exception as e:
        raise RestoreError(f"gzip 文件损坏或不可解压 {os.path.basename(path)}: {e}") from e


def _verify_sqlite(path: str) -> dict:
    """校验 SQLite 备份可打开且结构完整，返回 {"tables": [...], "integrity": str}"""
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
    """校验 tar.gz 可读，返回 {"members": n}。同时检查路径穿越。"""
    count = 0
    try:
        with tarfile.open(path, "r:gz") as tar:
            for member in tar:
                # 路径穿越防护：恢复时若直接解包，恶意/损坏的归档可能写出目录外
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
    """校验一份备份是否可用于恢复。

    deep=True 时完整解压校验（较慢但可靠）；False 时只检查文件存在与大小。
    返回校验报告 dict；失败抛 RestoreError。
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

    # 解压到临时目录后校验内容
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

            # 与 manifest 记录的表数量对比（manifest 不记录表数时跳过）
            manifest_tables = (info["manifest_data"] or {}).get("tables_count")
            if manifest_tables and manifest_tables != len(sqlite_info["tables"]):
                report["warnings"].append(
                    f"表数量与 manifest 记录不一致：manifest={manifest_tables}, "
                    f"实际={len(sqlite_info['tables'])}"
                )
        else:
            # PostgreSQL 的 .sql 文本备份：只做基本可读性检查
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


# ------------------------------------------------------------------ 恢复数据库
def restore_database(timestamp: str = None, force: bool = False,
                     target: str = None) -> dict:
    """从备份恢复数据库。

    默认拒绝覆盖已存在的库文件（恢复是破坏性操作）。
    force=True 时先把现有库另存为 <库文件>.pre_restore_<时间戳>，再写入。

    target 指定恢复到的库文件路径；为空时用当前 DATABASE_URL 指向的库。
    返回恢复报告 dict。
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

    # 恢复前先校验备份可用，避免写出半个库
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

    # 解压/复制到目标位置
    if db_path.endswith(".gz"):
        with gzip.open(db_path, "rb") as fin, open(dest, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        report["steps"].append("已从 gzip 解压写入目标库")
    else:
        shutil.copy2(db_path, dest)
        report["steps"].append("已复制备份文件到目标库")

    # 恢复后自检：结构 + 关键表行数
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
    """统计关键表行数（恢复后核对数据是否真的回来了）"""
    counts = {}
    con = sqlite3.connect(db_path)
    try:
        for table in CRITICAL_TABLES:
            safe = _safe_ident(table)
            try:
                # 表名无法参数化（SQL 占位符只能绑值，不能绑标识符），
                # 因此改用白名单校验：safe 已经过 _safe_ident 正则确认。
                counts[safe] = con.execute(
                    f'SELECT COUNT(*) FROM "{safe}"'  # nosec B608
                ).fetchone()[0]
            except sqlite3.Error:
                counts[safe] = None
    finally:
        con.close()
    return counts


def _foreign_key_check(db_path: str) -> list:
    """外键完整性检查，返回违规记录（最多 20 条）"""
    issues = []
    con = sqlite3.connect(db_path)
    try:
        # PRAGMA foreign_key_check 在未启用外键的连接上也可运行
        for row in con.execute("PRAGMA foreign_key_check"):
            issues.append({"table": row[0], "rowid": row[1], "parent": row[2]})
            if len(issues) >= 20:
                break
    except sqlite3.Error as e:
        logger.warning(f"外键检查失败: {e}")
    finally:
        con.close()
    return issues


# ------------------------------------------------------------------ 恢复材料文件
def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, dest: str) -> None:
    """解包单个成员。

    Python 3.12 起 tarfile.extract 未指定 filter 会告警，3.14 将改变默认行为；
    本项目需兼容 3.10，因此按版本选择：能用 filter 就用 filter="data"
    （它本身就带路径穿越防护），否则回落到已手工校验过路径的默认行为。
    """
    try:
        tar.extract(member, path=dest, filter="data")
    except TypeError:
        # Python < 3.12 不支持 filter 参数；路径已由调用方归一化校验
        tar.extract(member, path=dest)


def restore_files(timestamp: str = None, target: str = None) -> dict:
    """恢复材料文件。

    未指定 target 时解包到临时目录供人工核对（不直接覆盖生产材料目录，
    因为材料文件是客户原始资料，误覆盖代价高）。
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

    # 复用校验中的路径穿越检查
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


# ------------------------------------------------------------------ 演练
def drill(timestamp: str = None) -> dict:
    """恢复演练：在临时位置完整走一遍恢复流程并校验数据可读。

    全程不接触生产数据库与生产材料目录 —— 这是「备份是否真的可用」的
    可重复验证手段。建议每月或每次修改备份逻辑后执行一次。
    """
    info = find_backup(timestamp)
    ts = info["timestamp"]
    report = {"timestamp": ts, "ok": False, "steps": [], "warnings": []}

    # 1) 校验
    verification = verify_backup(ts)
    report["verification"] = {
        "tables_count": verification.get("tables_count"),
        "files_count": verification.get("files_count"),
        "checks": verification["checks"],
    }
    report["steps"].append("备份校验通过")

    with tempfile.TemporaryDirectory(prefix="trm_drill_") as tmp:
        # 2) 恢复数据库到临时文件
        tmp_db = os.path.join(tmp, "restored.sqlite")
        db_report = restore_database(ts, force=True, target=tmp_db)
        report["steps"].append(f"数据库已恢复到临时位置，{db_report['tables_count']} 张表")
        report["row_counts"] = db_report.get("row_counts")
        report["warnings"].extend(db_report.get("warnings", []))

        # 3) 数据可读性验证：真实查询关键业务对象
        readable = _readability_check(tmp_db)
        report["readability"] = readable
        if readable["ok"]:
            report["steps"].append(
                f"数据可读：{readable['users']} 用户 / {readable['customers']} 客户 / "
                f"{readable['applications']} 批次"
            )
        else:
            report["warnings"].append(f"数据可读性检查异常: {readable.get('error')}")

        # 4) 材料文件恢复到临时目录
        if info["files"]:
            files_report = restore_files(ts, target=os.path.join(tmp, "files"))
            report["steps"].append(f"材料文件已恢复到临时位置，{files_report['extracted']} 个文件")

    report["ok"] = True
    return report


def _readability_check(db_path: str) -> dict:
    """用真实查询验证恢复出的库可用（不只是能打开，还要能查出业务数据）"""
    result = {"ok": False, "users": 0, "customers": 0, "applications": 0}
    con = sqlite3.connect(db_path)
    try:
        for key, table in (("users", "users"), ("customers", "customers"),
                           ("applications", "applications")):
            # 同 _row_counts：标识符不能参数化，用 _safe_ident 白名单校验
            result[key] = con.execute(
                f'SELECT COUNT(*) FROM "{_safe_ident(table)}"'  # nosec B608
            ).fetchone()[0]
        # 抽样一条客户记录，确认字段可正常读取
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
