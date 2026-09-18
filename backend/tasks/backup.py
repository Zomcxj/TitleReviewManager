#!/usr/bin/env python3
"""
数据自动备份（数据库 + 材料文件）

背景：平台同时保存业务数据（SQLite / PostgreSQL）和材料原文件（本地目录或挂载的
NAS）。此前没有任何自动备份，一旦磁盘损坏或误删，业务数据与客户材料无法恢复。
本模块提供一次完整的备份能力，可被三种方式触发：
1) 内置调度器（utils/scheduler.py）每天固定小时自动执行
2) 管理端 API（routers/backup.py）手动触发
3) 外部 cron 直接执行 `python tasks/backup.py`

设计要点
- 数据库必须"一致性"备份：SQLite 用官方 backup API（直接复制写入中的文件会得到
  损坏的库）；PostgreSQL 用 pg_dump。
- 材料文件用标准库 tarfile 打包，不引入新依赖。
- 任何异常只记日志并写入结果摘要，绝不向上抛出（备份失败不能影响业务）。
- 保留最近 BACKUP_KEEP 份，超出自动清理最旧的（连同 manifest）。
- 每份备份在同一目录写一个 manifest_<timestamp>.json，记录备份元信息，便于
  恢复时核对与界面展示。

环境变量（均有合理默认）
- BACKUP_ENABLED      默认 1，是否启用自动备份
- BACKUP_DIR          默认 backend/backups
- BACKUP_KEEP         默认 7，保留份数
- BACKUP_HOUR         默认 3，每天几点执行（调度器按小时判断）
- BACKUP_INCLUDE_FILES 默认 1，是否同时打包材料文件
- BACKUP_COMPRESS     默认 1，是否 gzip 压缩数据库备份

备份产物（同一目录）
- db_<timestamp>.sqlite.gz 或 db_<timestamp>.sql      数据库备份
- files_<timestamp>.tar.gz                            材料文件打包（可选）
- manifest_<timestamp>.json                           备份元信息

恢复步骤（详见 .env.example 注释）
1. 停掉后端服务（避免恢复过程中仍有写入）。
2. SQLite：
   - 解压 `gzip -dk db_<ts>.sqlite.gz` 得到 db_<ts>.sqlite
   - 用解压出的文件替换 DATABASE_URL 指向的库文件（先备份现有文件）
3. PostgreSQL：
   - 解压 `gzip -dk db_<ts>.sql.gz`
   - `psql -U <user> -d <db> -f db_<ts>.sql`（建议先建空库）
4. 材料文件：
   - 在 storage.get_storage_root() 指向的目录内解包
     `tar -xzf files_<ts>.tar.gz -C <storage_root>`
5. 重启服务，核对 manifest_<ts>.json 中的记录（大小/数量/是否成功）。
"""
import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# backend/ 目录（本文件位于 backend/tasks/）
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BACKUP_DIR = os.path.join(BACKEND_DIR, "backups")

# 时间戳格式：文件名与 manifest 分组都依赖它，保持唯一且可排序
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
# 备份文件名 -> 时间戳（db_20260918_020000.sqlite.gz / files_... / manifest_...）
_TS_RE = re.compile(r"^(?:db|files|manifest)_(\d{8}_\d{6})\.")

# 标记文件：记录最近一次备份尝试的日期，避免同一小时内重复备份
_MARKER_NAME = "_last_backup.marker"


# ---------------------------------------------------------------- 配置读取
def _env_flag(name: str, default: bool = True) -> bool:
    """读取布尔型环境变量（1/true/yes/on 视为真）"""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _env_int(name: str, default: int) -> int:
    """读取整型环境变量，非法值回落默认值"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(f"环境变量 {name}={raw!r} 不是合法整数，使用默认值 {default}")
        return default


def get_backup_dir() -> str:
    """备份目录（BACKUP_DIR，默认 backend/backups）"""
    return os.getenv("BACKUP_DIR") or DEFAULT_BACKUP_DIR


def is_enabled() -> bool:
    """自动备份是否启用（BACKUP_ENABLED，默认 1）"""
    return _env_flag("BACKUP_ENABLED", True)


def get_keep() -> int:
    """保留份数（BACKUP_KEEP，默认 7；<1 时按 1 处理）"""
    return max(_env_int("BACKUP_KEEP", 7), 1)


def get_hour() -> int:
    """每日执行小时（BACKUP_HOUR，默认 3），非法值回落 3"""
    hour = _env_int("BACKUP_HOUR", 3)
    return hour if 0 <= hour <= 23 else 3


def include_files_enabled() -> bool:
    """是否同时打包材料文件（BACKUP_INCLUDE_FILES，默认 1）"""
    return _env_flag("BACKUP_INCLUDE_FILES", True)


def compress_enabled() -> bool:
    """是否 gzip 压缩数据库备份（BACKUP_COMPRESS，默认 1）"""
    return _env_flag("BACKUP_COMPRESS", True)


def get_backup_config() -> dict:
    """返回当前备份配置（供管理端展示，不含敏感信息）"""
    return {
        "BACKUP_ENABLED": is_enabled(),
        "BACKUP_DIR": get_backup_dir(),
        "BACKUP_KEEP": get_keep(),
        "BACKUP_HOUR": get_hour(),
        "BACKUP_INCLUDE_FILES": include_files_enabled(),
        "BACKUP_COMPRESS": compress_enabled(),
    }


# ---------------------------------------------------------------- 辅助函数
def _now() -> datetime:
    return datetime.now()


def _db_url() -> str:
    """当前数据库连接串（延迟导入，避免与 database/main 形成导入环）"""
    from database import DATABASE_URL
    return str(DATABASE_URL)


def _db_type() -> str:
    """返回 'sqlite' / 'postgresql' / 'unknown'"""
    url = _db_url().lower()
    if url.startswith("sqlite"):
        return "sqlite"
    if url.startswith("postgres"):
        return "postgresql"
    return "unknown"


def _sqlite_db_path() -> str:
    """从 DATABASE_URL 解析 SQLite 文件绝对路径"""
    url = _db_url()
    if ":memory:" in url:
        raise RuntimeError("当前为内存数据库（:memory:），无法备份为文件")
    if ":///" in url:
        path = url.split(":///", 1)[1]
    else:
        raise RuntimeError(f"无法解析 SQLite 连接串: {url}")
    if not path:
        raise RuntimeError(f"无法解析 SQLite 文件路径: {url}")
    return os.path.abspath(path)


def _app_version():
    """应用版本号（优先环境变量 APP_VERSION，其次 main.app.version）"""
    v = os.getenv("APP_VERSION")
    if v:
        return v
    try:
        from main import app as _app
        return getattr(_app, "version", None)
    except Exception:
        return None


def _storage_stats(root: str) -> tuple:
    """统计目录下文件数量与原始总字节数 -> (count, total_size)"""
    count, total = 0, 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                total += os.path.getsize(full)
                count += 1
            except OSError:
                # 单个文件不可读（权限/被占用）不应让整体统计失败
                continue
    return count, total


def _gzip_file(src: str, dest: str) -> None:
    """用标准库 gzip 压缩文件（流式，避免大库一次性读入内存）"""
    with open(src, "rb") as fin, gzip.open(dest, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)


# ---------------------------------------------------------------- 数据库备份
def _backup_sqlite(dest_dir: str, timestamp: str) -> tuple:
    """备份 SQLite 数据库（一致性备份）。

    使用 sqlite3 官方 backup API：即使数据库正在被写入，也能得到一致的快照；
    直接复制文件在写入过程中会得到损坏的库。
    若当前 Python/驱动不支持 backup API，退化为文件复制并记警告。

    返回 (备份文件路径, 原始未压缩字节数)。
    """
    src = _sqlite_db_path()
    if not os.path.exists(src):
        raise RuntimeError(f"SQLite 数据库文件不存在: {src}")

    raw_dest = os.path.join(dest_dir, f"db_{timestamp}.sqlite")
    # 清理可能残留的同名半成品
    if os.path.exists(raw_dest):
        os.remove(raw_dest)

    used_backup_api = False
    try:
        src_con = sqlite3.connect(src)
        try:
            if hasattr(src_con, "backup"):
                dst_con = sqlite3.connect(raw_dest)
                try:
                    with dst_con:
                        src_con.backup(dst_con)
                    used_backup_api = True
                finally:
                    dst_con.close()
            else:
                raise AttributeError("sqlite3.Connection 不支持 backup API")
        finally:
            src_con.close()
    except Exception as e:
        logger.warning(f"SQLite backup API 不可用（{e}），退化为文件复制，可能存在一致性风险")
        if os.path.exists(raw_dest):
            try:
                os.remove(raw_dest)
            except OSError:
                pass
        shutil.copy2(src, raw_dest)

    size = os.path.getsize(raw_dest)
    if used_backup_api:
        logger.info(f"SQLite 一致性备份完成: {raw_dest} ({size} bytes)")
    else:
        logger.warning(f"SQLite 文件复制备份完成（非一致性）: {raw_dest} ({size} bytes)")

    if compress_enabled():
        gz_path = raw_dest + ".gz"
        _gzip_file(raw_dest, gz_path)
        os.remove(raw_dest)
        logger.info(f"SQLite 备份已压缩: {gz_path} ({os.path.getsize(gz_path)} bytes)")
        return gz_path, size

    return raw_dest, size


def _backup_postgres(dest_dir: str, timestamp: str) -> tuple:
    """备份 PostgreSQL 数据库（调用 pg_dump）。

    pg_dump 不存在时抛出带安装指引的 RuntimeError。
    返回 (备份文件路径, 原始未压缩字节数)。
    """
    url = _db_url()
    # SQLAlchemy 方言前缀（postgresql+psycopg2://）不是 pg_dump 认识的连接串
    dsn = re.sub(r"^postgresql\+[a-z0-9_]+://", "postgresql://", url, flags=re.I)
    dsn = re.sub(r"^postgres://", "postgresql://", dsn, flags=re.I)

    raw_dest = os.path.join(dest_dir, f"db_{timestamp}.sql")
    if os.path.exists(raw_dest):
        os.remove(raw_dest)

    cmd = ["pg_dump", "--no-owner", "--no-privileges", "--dbname", dsn]
    try:
        with open(raw_dest, "wb") as fout:
            proc = subprocess.run(
                cmd,
                stdout=fout,
                stderr=subprocess.PIPE,
                check=False,
                # Windows 下 pg_dump 是 exe，列表参数无需 shell，避免注入与转义问题
                shell=False,
            )
    except FileNotFoundError:
        if os.path.exists(raw_dest):
            os.remove(raw_dest)
        raise RuntimeError(
            "未找到 pg_dump 可执行文件。请安装 postgresql-client 或在容器内执行"
            "（Debian/Ubuntu: apt-get install postgresql-client；"
            "Alpine: apk add postgresql-client；Dockerfile 中请加入该包）"
        )
    except OSError as e:
        if os.path.exists(raw_dest):
            os.remove(raw_dest)
        raise RuntimeError(f"调用 pg_dump 失败: {e}")

    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        if os.path.exists(raw_dest):
            os.remove(raw_dest)
        raise RuntimeError(f"pg_dump 退出码 {proc.returncode}: {stderr[:500]}")

    size = os.path.getsize(raw_dest)
    if size == 0:
        os.remove(raw_dest)
        raise RuntimeError("pg_dump 输出为空，备份失败")
    logger.info(f"PostgreSQL 备份完成: {raw_dest} ({size} bytes)")

    if compress_enabled():
        gz_path = raw_dest + ".gz"
        _gzip_file(raw_dest, gz_path)
        os.remove(raw_dest)
        logger.info(f"PostgreSQL 备份已压缩: {gz_path} ({os.path.getsize(gz_path)} bytes)")
        return gz_path, size

    return raw_dest, size


# ---------------------------------------------------------------- 材料文件备份
def _backup_files(dest_dir: str, timestamp: str) -> tuple:
    """打包材料存储根目录（storage.get_storage_root()）。

    返回 (tar.gz 路径, 打包的文件数量)。
    """
    from storage import get_storage_root

    root = get_storage_root()
    if not os.path.isdir(root):
        raise RuntimeError(f"材料存储目录不存在: {root}")

    tar_path = os.path.join(dest_dir, f"files_{timestamp}.tar.gz")
    if os.path.exists(tar_path):
        os.remove(tar_path)

    count = 0
    # 逐个文件加入（而不是 add 整个目录），既便于计数，也避免把根目录本身
    # 带进归档导致解包时多出一层目录
    with tarfile.open(tar_path, "w:gz") as tar:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root).replace("\\", "/")
                try:
                    tar.add(full, arcname=rel)
                    count += 1
                except OSError as e:
                    # 单个文件被占用/无权限时跳过，不中断整体备份
                    logger.warning(f"材料文件打包跳过 {rel}: {e}")

    logger.info(f"材料文件备份完成: {tar_path}（{count} 个文件）")
    return tar_path, count


# ---------------------------------------------------------------- manifest
def _write_manifest(dest_dir: str, timestamp: str, data: dict) -> str:
    """写入 manifest_<timestamp>.json，返回文件路径"""
    path = os.path.join(dest_dir, f"manifest_{timestamp}.json")
    payload = dict(data)
    payload.setdefault("timestamp", timestamp)
    payload.setdefault("backup_time", _now().isoformat())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _read_manifest(path: str):
    """读取 manifest，损坏时返回 None（不影响其他备份的展示）"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"读取备份清单失败 {path}: {e}")
        return None


def _scan_manifests(dest_dir: str) -> list:
    """扫描目录下所有 manifest -> [(timestamp, path, data)]"""
    result = []
    if not os.path.isdir(dest_dir):
        return result
    for name in os.listdir(dest_dir):
        if not name.startswith("manifest_") or not name.endswith(".json"):
            continue
        path = os.path.join(dest_dir, name)
        data = _read_manifest(path)
        ts = (data or {}).get("timestamp") or name[len("manifest_"):-len(".json")]
        result.append((ts, path, data or {}))
    return result


def _timestamp_of(filename: str):
    """从备份文件名解析时间戳，不匹配返回 None"""
    m = _TS_RE.match(filename)
    return m.group(1) if m else None


def _files_for_timestamp(dest_dir: str, timestamp: str) -> list:
    """列出属于某次备份的所有文件（db_/files_/manifest_）"""
    matched = []
    for name in os.listdir(dest_dir):
        if _timestamp_of(name) == timestamp:
            matched.append(os.path.join(dest_dir, name))
    return matched


def _cleanup_old(dest_dir: str, keep: int) -> list:
    """按保留份数清理旧备份，返回被删除的文件名列表。

    以 manifest 的时间戳分组（每次备份的 db/files/manifest 三件套同一时间戳），
    保留最新的 keep 份，其余连同 manifest 一起删除；同时清理早于最旧保留份的
    孤立文件（例如 manifest 写入失败留下的残留）。
    """
    deleted = []
    if keep <= 0 or not os.path.isdir(dest_dir):
        return deleted

    entries = _scan_manifests(dest_dir)
    entries.sort(key=lambda e: e[0], reverse=True)
    kept = {e[0] for e in entries[:keep]}

    for ts, _path, _data in entries[keep:]:
        for full in _files_for_timestamp(dest_dir, ts):
            try:
                os.remove(full)
                deleted.append(os.path.basename(full))
            except OSError as e:
                logger.warning(f"清理旧备份失败 {full}: {e}")

    # 孤立文件清理：时间戳早于最旧保留份的才删，避免误删刚生成但 manifest 未写成的备份
    if entries:
        oldest_kept = min(kept)
        for name in os.listdir(dest_dir):
            ts = _timestamp_of(name)
            if not ts or ts in kept or ts >= oldest_kept:
                continue
            full = os.path.join(dest_dir, name)
            try:
                os.remove(full)
                deleted.append(name)
            except OSError as e:
                logger.warning(f"清理孤立备份文件失败 {full}: {e}")

    if deleted:
        logger.info(f"已清理 {len(deleted)} 个过期备份文件: {deleted}")
    return deleted


# ---------------------------------------------------------------- 主流程
def run_backup(include_files: bool = None) -> dict:
    """执行一次完整备份（数据库 + 可选材料文件）。

    参数
    - include_files: 是否打包材料文件；None 时取 BACKUP_INCLUDE_FILES

    返回结果摘要：
    {"success", "db_backup", "files_backup", "manifest",
     "duration_seconds", "error", "cleaned"}

    数据库与文件备份任一失败都只记录在结果里，绝不抛异常（备份不能影响业务）。
    """
    started = time.time()
    timestamp = _now().strftime(TIMESTAMP_FORMAT)
    dest_dir = get_backup_dir()
    if include_files is None:
        include_files = include_files_enabled()

    result = {
        "success": False,
        "timestamp": timestamp,
        "db_backup": None,
        "files_backup": None,
        "manifest": None,
        "duration_seconds": 0.0,
        "error": None,
        "cleaned": [],
    }

    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        result["error"] = f"无法创建备份目录 {dest_dir}: {e}"
        result["duration_seconds"] = round(time.time() - started, 3)
        logger.error(result["error"])
        return result

    errors = []
    db_type = _db_type()
    db_size = 0
    files_count = 0
    files_total = 0
    files_backup_path = None

    # ---- 1) 数据库备份 ----
    try:
        if db_type == "sqlite":
            db_path, db_size = _backup_sqlite(dest_dir, timestamp)
            result["db_backup"] = db_path
        elif db_type == "postgresql":
            db_path, db_size = _backup_postgres(dest_dir, timestamp)
            result["db_backup"] = db_path
        else:
            raise RuntimeError(f"不支持的数据库类型: {_db_url().split('://')[0]}")
    except Exception as e:
        errors.append(f"数据库备份失败: {e}")
        logger.error(f"数据库备份失败: {e}", exc_info=True)

    # ---- 2) 材料文件备份 ----
    if include_files:
        try:
            from storage import get_storage_root
            storage_root = get_storage_root()
            files_count, files_total = _storage_stats(storage_root)
            files_backup_path, files_count = _backup_files(dest_dir, timestamp)
            result["files_backup"] = files_backup_path
        except Exception as e:
            errors.append(f"材料文件备份失败: {e}")
            logger.error(f"材料文件备份失败: {e}", exc_info=True)

    # ---- 3) 写 manifest（无论成功失败都写，便于排查与"今日是否已备份"判断）----
    result["error"] = "；".join(errors) if errors else None
    result["success"] = result["db_backup"] is not None and not errors
    result["duration_seconds"] = round(time.time() - started, 3)

    manifest_data = {
        "timestamp": timestamp,
        "backup_time": _now().isoformat(),
        "db_type": db_type,
        "db_backup_file": os.path.basename(result["db_backup"]) if result["db_backup"] else None,
        "db_file_size_bytes": db_size,
        "files_backup_file": os.path.basename(files_backup_path) if files_backup_path else None,
        "files_backup_size_bytes": os.path.getsize(files_backup_path) if files_backup_path and os.path.exists(files_backup_path) else 0,
        "files_count": files_count,
        "files_total_size_bytes": files_total,
        "app_version": _app_version(),
        "success": result["success"],
        "error": result["error"],
        "duration_seconds": result["duration_seconds"],
        "backup_dir": dest_dir,
    }
    try:
        result["manifest"] = _write_manifest(dest_dir, timestamp, manifest_data)
    except Exception as e:
        errors.append(f"写入备份清单失败: {e}")
        result["error"] = "；".join(errors)
        result["success"] = False
        logger.error(f"写入备份清单失败: {e}", exc_info=True)

    # ---- 4) 标记文件（供调度器判断"今天是否已成功备份"，避免同小时重复执行）----
    # 仅在成功时写入：失败时保留重试机会（受 BACKUP_HOUR 小时判断约束，
    # 因此同一天内最多在该小时窗口内重试，不会造成频繁重试）
    if result["success"]:
        try:
            with open(os.path.join(dest_dir, _MARKER_NAME), "w", encoding="utf-8") as f:
                f.write(_now().strftime("%Y-%m-%d"))
        except OSError as e:
            logger.warning(f"写入备份标记文件失败（不影响备份结果）: {e}")

    # ---- 5) 清理超出保留份数的旧备份 ----
    try:
        result["cleaned"] = _cleanup_old(dest_dir, get_keep())
    except Exception as e:
        logger.warning(f"清理旧备份失败（不影响本次备份）: {e}")

    if result["success"]:
        logger.info(
            f"备份完成: db={result['db_backup']} files={result['files_backup']} "
            f"耗时 {result['duration_seconds']}s"
        )
    else:
        logger.error(f"备份失败: {result['error']}")
    return result


# ---------------------------------------------------------------- 查询 / 调度辅助
def list_backups() -> list:
    """列出所有备份（读 manifest，按时间倒序），供管理端 API 使用。

    每个元素为 manifest 内容，额外附带 "manifest_file" 字段。
    """
    dest_dir = get_backup_dir()
    items = []
    for ts, path, data in _scan_manifests(dest_dir):
        item = dict(data)
        item.setdefault("timestamp", ts)
        item["manifest_file"] = os.path.basename(path)
        item["backup_dir"] = dest_dir
        items.append(item)
    items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return items


def last_backup_time(success_only: bool = True):
    """最近一次备份时间（datetime），无记录返回 None。

    success_only=True（默认）时只统计成功的备份，供调度器判断"今天是否已备份"；
    失败记录不应阻止当天的重试。
    """
    latest = None
    for item in list_backups():
        if success_only and not item.get("success"):
            continue
        raw = item.get("backup_time") or ""
        try:
            dt = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            ts = item.get("timestamp") or ""
            try:
                dt = datetime.strptime(ts, TIMESTAMP_FORMAT)
            except ValueError:
                continue
        if latest is None or dt > latest:
            latest = dt
    return latest


def _last_success_date():
    """最近一次成功备份的日期字符串（YYYY-MM-DD），无记录返回 None。

    优先读标记文件（成功时写入），回落到扫描 manifest 中成功的记录。
    """
    marker = os.path.join(get_backup_dir(), _MARKER_NAME)
    if os.path.exists(marker):
        try:
            with open(marker, "r", encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
        except OSError:
            pass
    last = last_backup_time(success_only=True)
    return last.strftime("%Y-%m-%d") if last else None


def should_run_now(now: datetime = None) -> bool:
    """调度器判断：当前是否应执行自动备份。

    规则：备份已启用 && 当前小时 == BACKUP_HOUR && 今天尚未成功备份过。
    同时使用标记文件与 manifest 最新成功时间判断，避免每小时重复备份；
    失败不写标记，因此同一天内仍可重试。
    """
    if not is_enabled():
        return False
    now = now or _now()
    if now.hour != get_hour():
        return False
    if _last_success_date() == now.strftime("%Y-%m-%d"):
        return False
    return True


if __name__ == "__main__":
    # 便于外部 cron 直接调用：python tasks/backup.py
    # 直接以脚本方式执行时，脚本目录是 backend/tasks，backend 不在 sys.path 上，
    # 需要手动加入，否则 from database / storage 等导入会失败。
    import sys

    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    outcome = run_backup()
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    # 失败时以非 0 退出码结束，方便 cron 告警（不影响调度器内调用）
    raise SystemExit(0 if outcome["success"] else 1)
