#!/usr/bin/env python3
"""
Automatic data backup (database + material files)

Background: the platform stores both business data (SQLite / PostgreSQL) and the
original material files (local directory or mounted NAS). There was no automatic
backup at all; a damaged disk or accidental deletion meant business data and
customer materials were unrecoverable. This module provides one complete backup
capability, triggered in three ways:
1) The built-in scheduler (utils/scheduler.py) runs it automatically at a fixed hour each day
2) The admin API (routers/backup.py) triggers it manually
3) External cron runs `python tasks/backup.py` directly

Design notes
- The database must be backed up "consistently": SQLite uses the official backup API
  (directly copying a file being written to yields a corrupt database); PostgreSQL uses pg_dump.
- Material files are packed with the stdlib tarfile; no new dependencies.
- Any exception is only logged and written into the result summary, never raised
  (a backup failure must not affect the business).
- Keeps the most recent BACKUP_KEEP copies; older ones (and their manifests) are cleaned up.
- Each backup writes a manifest_<timestamp>.json into the same directory with backup
  metadata, for verification during restore and for the UI.

Environment variables (all have sane defaults)
- BACKUP_ENABLED      default 1, whether automatic backup is enabled
- BACKUP_DIR          default backend/backups
- BACKUP_KEEP         default 7, copies to keep
- BACKUP_HOUR         default 3, hour of day to run (the scheduler checks by hour)
- BACKUP_INCLUDE_FILES default 1, whether to also pack material files
- BACKUP_COMPRESS     default 1, whether to gzip the database backup

Backup artifacts (same directory)
- db_<timestamp>.sqlite.gz or db_<timestamp>.sql      database backup
- files_<timestamp>.tar.gz                            packed material files (optional)
- manifest_<timestamp>.json                           backup metadata

Restore steps (see the .env.example comments for details)
1. Stop the backend (avoid writes during the restore).
2. SQLite:
   - Extract `gzip -dk db_<ts>.sqlite.gz` to get db_<ts>.sqlite
   - Replace the database file pointed to by DATABASE_URL with the extracted file
     (back up the existing file first)
3. PostgreSQL:
   - Extract `gzip -dk db_<ts>.sql.gz`
   - `psql -U <user> -d <db> -f db_<ts>.sql` (create an empty database first, recommended)
4. Material files:
   - Unpack inside the directory pointed to by storage.get_storage_root():
     `tar -xzf files_<ts>.tar.gz -C <storage_root>`
5. Restart the service and verify the records in manifest_<ts>.json (sizes/counts/success).
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
from contextlib import suppress
from datetime import datetime

logger = logging.getLogger(__name__)

# backend/ directory (this file lives in backend/tasks/)
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BACKUP_DIR = os.path.join(BACKEND_DIR, "backups")

# Timestamp format: both filenames and manifest grouping depend on it; keep it unique and sortable
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
# Backup filename -> timestamp (db_20260918_020000.sqlite.gz / files_... / manifest_...)
_TS_RE = re.compile(r"^(?:db|files|manifest)_(\d{8}_\d{6})\.")

# Marker file: records the date of the most recent backup attempt, avoiding duplicate backups within the same hour
_MARKER_NAME = "_last_backup.marker"


# ---------------------------------------------------------------- config reading
def _env_flag(name: str, default: bool = True) -> bool:
    """Read a boolean env var (1/true/yes/on are truthy)"""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to the default on invalid values"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(f"环境变量 {name}={raw!r} 不是合法整数，使用默认值 {default}")
        return default


def get_backup_dir() -> str:
    """Backup directory (BACKUP_DIR, default backend/backups)"""
    return os.getenv("BACKUP_DIR") or DEFAULT_BACKUP_DIR


# Command to push an offsite copy after a successful backup (BACKUP_SYNC_CMD, empty by default = disabled).
# {backup_dir} in the template is replaced with this backup's directory; example:
#   rsync -a --delete {backup_dir}/ /mnt/disk2/trm-backups/
# Timeout in seconds (BACKUP_SYNC_TIMEOUT), so a hung sync command cannot stall the scheduler thread
SYNC_TIMEOUT_SECONDS = _env_int("BACKUP_SYNC_TIMEOUT", 600)


def is_enabled() -> bool:
    """Whether automatic backup is enabled (BACKUP_ENABLED, default 1)"""
    return _env_flag("BACKUP_ENABLED", True)


def get_keep() -> int:
    """Copies to keep (BACKUP_KEEP, default 7; values <1 are treated as 1)"""
    return max(_env_int("BACKUP_KEEP", 7), 1)


def get_hour() -> int:
    """Hour of day to run (BACKUP_HOUR, default 3); invalid values fall back to 3"""
    hour = _env_int("BACKUP_HOUR", 3)
    return hour if 0 <= hour <= 23 else 3


def include_files_enabled() -> bool:
    """Whether to also pack material files (BACKUP_INCLUDE_FILES, default 1)"""
    return _env_flag("BACKUP_INCLUDE_FILES", True)


def compress_enabled() -> bool:
    """Whether to gzip the database backup (BACKUP_COMPRESS, default 1)"""
    return _env_flag("BACKUP_COMPRESS", True)


def get_backup_config() -> dict:
    """Return the current backup configuration (for the admin UI, no sensitive values)"""
    return {
        "BACKUP_ENABLED": is_enabled(),
        "BACKUP_DIR": get_backup_dir(),
        "BACKUP_KEEP": get_keep(),
        "BACKUP_HOUR": get_hour(),
        "BACKUP_INCLUDE_FILES": include_files_enabled(),
        "BACKUP_COMPRESS": compress_enabled(),
    }


# ---------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now()


def _db_url() -> str:
    """Current database connection string (lazy import, avoiding an import cycle with database/main)"""
    from database import DATABASE_URL
    return str(DATABASE_URL)


def _db_type() -> str:
    """Return 'sqlite' / 'postgresql' / 'unknown'"""
    url = _db_url().lower()
    if url.startswith("sqlite"):
        return "sqlite"
    if url.startswith("postgres"):
        return "postgresql"
    return "unknown"


def _sqlite_db_path() -> str:
    """Resolve the SQLite file's absolute path from DATABASE_URL"""
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
    """Application version (prefers the APP_VERSION env var, then main.app.version)"""
    v = os.getenv("APP_VERSION")
    if v:
        return v
    try:
        from main import app as _app
        return getattr(_app, "version", None)
    except Exception:
        return None


def _storage_stats(root: str) -> tuple:
    """Count files and total raw bytes under a directory -> (count, total_size)"""
    count, total = 0, 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                total += os.path.getsize(full)
                count += 1
            except OSError:
                # One unreadable file (permissions/locked) must not fail the overall stats
                continue
    return count, total


def _gzip_file(src: str, dest: str) -> None:
    """Compress a file with the stdlib gzip (streaming, so a large database is never fully read into memory)"""
    with open(src, "rb") as fin, gzip.open(dest, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)


# ---------------------------------------------------------------- database backup
def _backup_sqlite(dest_dir: str, timestamp: str) -> tuple:
    """Back up the SQLite database (consistent backup).

    Uses the official sqlite3 backup API: even while the database is being written,
    it yields a consistent snapshot; directly copying the file mid-write produces a
    corrupt database. If the current Python/driver lacks the backup API, falls back
    to file copy with a warning.

    Returns (backup file path, raw uncompressed byte count).
    """
    src = _sqlite_db_path()
    if not os.path.exists(src):
        raise RuntimeError(f"SQLite 数据库文件不存在: {src}")

    raw_dest = os.path.join(dest_dir, f"db_{timestamp}.sqlite")
    # Clean up a possibly leftover half-written file of the same name
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
            with suppress(OSError):
                os.remove(raw_dest)
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
    """Back up the PostgreSQL database (via pg_dump).

    Raises a RuntimeError with installation guidance when pg_dump is missing.
    Returns (backup file path, raw uncompressed byte count).
    """
    url = _db_url()
    # A SQLAlchemy dialect prefix (postgresql+psycopg2://) is not a connection string pg_dump understands
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
                # On Windows pg_dump is an exe; list args need no shell, avoiding injection and escaping issues
                shell=False,
            )
    except FileNotFoundError as e:
        if os.path.exists(raw_dest):
            os.remove(raw_dest)
        raise RuntimeError(
            "未找到 pg_dump 可执行文件。请安装 postgresql-client 或在容器内执行"
            "（Debian/Ubuntu: apt-get install postgresql-client；"
            "Alpine: apk add postgresql-client；Dockerfile 中请加入该包）"
        ) from e
    except OSError as e:
        if os.path.exists(raw_dest):
            os.remove(raw_dest)
        raise RuntimeError(f"调用 pg_dump 失败: {e}") from e

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


# ---------------------------------------------------------------- material file backup
def _backup_files(dest_dir: str, timestamp: str) -> tuple:
    """Pack the material storage root directory (storage.get_storage_root()).

    Returns (tar.gz path, number of files packed).
    """
    from storage import get_storage_root

    root = get_storage_root()
    if not os.path.isdir(root):
        raise RuntimeError(f"材料存储目录不存在: {root}")

    tar_path = os.path.join(dest_dir, f"files_{timestamp}.tar.gz")
    if os.path.exists(tar_path):
        os.remove(tar_path)

    count = 0
    # Add files one by one (rather than adding the whole directory): easier counting, and
    # avoids dragging the root directory itself into the archive (extra level on extraction)
    with tarfile.open(tar_path, "w:gz") as tar:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root).replace("\\", "/")
                try:
                    tar.add(full, arcname=rel)
                    count += 1
                except OSError as e:
                    # Skip files that are locked/permission-denied; never abort the whole backup
                    logger.warning(f"材料文件打包跳过 {rel}: {e}")

    logger.info(f"材料文件备份完成: {tar_path}（{count} 个文件）")
    return tar_path, count


# ---------------------------------------------------------------- manifest
def _write_manifest(dest_dir: str, timestamp: str, data: dict) -> str:
    """Write manifest_<timestamp>.json and return the file path"""
    path = os.path.join(dest_dir, f"manifest_{timestamp}.json")
    payload = dict(data)
    payload.setdefault("timestamp", timestamp)
    payload.setdefault("backup_time", _now().isoformat())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _read_manifest(path: str):
    """Read a manifest; returns None when corrupt (other backups still display)"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"读取备份清单失败 {path}: {e}")
        return None


def _scan_manifests(dest_dir: str) -> list:
    """Scan all manifests in a directory -> [(timestamp, path, data)]"""
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
    """Parse a timestamp from a backup filename; returns None on no match"""
    m = _TS_RE.match(filename)
    return m.group(1) if m else None


def _files_for_timestamp(dest_dir: str, timestamp: str) -> list:
    """List all files belonging to one backup (db_/files_/manifest_)"""
    matched = []
    for name in os.listdir(dest_dir):
        if _timestamp_of(name) == timestamp:
            matched.append(os.path.join(dest_dir, name))
    return matched


def _cleanup_old(dest_dir: str, keep: int) -> list:
    """Clean up old backups per the retention count; returns the deleted filenames.

    Groups by manifest timestamp (each backup's db/files/manifest trio shares one
    timestamp), keeps the newest keep copies and deletes the rest along with their
    manifests; also cleans up orphan files older than the oldest kept copy
    (e.g. leftovers from a failed manifest write).
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

    # Orphan cleanup: only delete files older than the oldest kept copy, sparing fresh backups whose manifest failed to write
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


# ---------------------------------------------------------------- main flow
def _notify_admins(title: str, content: str) -> None:
    """Send a backup-domain alert to all admins (in-app + configured external channels).

    All backup-domain failures (backup itself failing / offsite copy push failing)
    go through here: nobody reads logs proactively, alerts get things handled.
    Alert failures are only logged and never affect the backup flow.
    """
    try:
        from database import SessionLocal
        from models import User
        from routers.notifications import create_notification

        db = SessionLocal()
        try:
            admins = db.query(User).filter(
                User.role == "admin", User.is_deleted == False  # noqa: E712
            ).all()
            for admin in admins:
                create_notification(
                    db=db, user_id=admin.id, title=title, content=content,
                    type="backup_failed", related_type="backup",
                    related_id=None,
                )
            db.commit()
            logger.info(f"备份告警「{title}」已通知 {len(admins)} 位管理员")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        # An alert failure must not, in turn, affect the backup result
        logger.error(f"发送备份告警时出错: {e}", exc_info=True)


def _notify_backup_failure(result: dict) -> None:
    """Notify admins when a backup fails.

    Backup failures used to be log-only — unread logs mean the failure was silently
    swallowed. The backup is the only line between "total data loss" and "nothing
    happened"; failures must be made known.
    """
    error = result.get("error") or "未知原因"
    _notify_admins(
        "自动备份失败",
        f"时间点 {result.get('timestamp')} 的自动备份失败：{error}。"
        "请尽快检查备份目录磁盘空间与数据库连接，备份失效意味着数据无法恢复。",
    )


def _notify_offsite_sync_failure(result: dict, error: str) -> None:
    """An offsite copy push failure must alert: the local backup is fine, but disaster-recovery capability is still zero. Never silent."""
    _notify_admins(
        "备份副本同步失败",
        f"时间点 {result.get('timestamp')} 的备份已在本机完成，"
        f"但推送到异机/异盘失败：{error}。"
        "本地备份与数据库仍在同一台机器上，宿主机损坏时两者一起丢失，请尽快处理同步通道。",
    )


def _run_offsite_sync(result: dict) -> None:
    """After a successful backup, run the optional offsite copy push command (BACKUP_SYNC_CMD, off by default).

    Background: by default the backup directory and the database sit on the same
    host — if the host dies, both are lost, the biggest single point of failure of
    single-host deployment. Once a sync command is configured, every successful
    backup automatically pushes a copy to another machine/disk/object storage; the
    {backup_dir} placeholder in the command template is replaced with this backup's directory.

    Security boundary: the command runs with the application process's identity and
    permissions and is an admin-level setting (trusted at the same level as
    DATABASE_URL / JWT_SECRET_KEY) — by default it is unset and executes nothing.

    Contract: a sync failure does not overturn the backup's own success (the local
    backup is intact), but it must alert. This function never raises, matching
    run_backup's overall contract.
    """
    cmd = (os.getenv("BACKUP_SYNC_CMD") or "").strip()
    result["offsite_sync"] = None
    if not cmd:
        return

    if "{backup_dir}" in cmd:
        cmd = cmd.replace("{backup_dir}", result.get("backup_dir") or "")

    started = time.time()
    try:
        # shell=True is a deliberate choice: rsync/rclone pipelines (e.g. age|rclone) need a shell.
        # The command comes from admin configuration, not user input; trusted like other env vars.
        proc = subprocess.run(  # nosec B602
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=SYNC_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        error = f"同步命令超过 {SYNC_TIMEOUT_SECONDS}s 已终止"
        logger.error(f"备份副本同步失败: {error}")
        result["offsite_sync"] = {"ok": False, "error": error}
        _notify_offsite_sync_failure(result, error)
        return
    except Exception as e:
        logger.error(f"备份副本同步失败: {e}", exc_info=True)
        result["offsite_sync"] = {"ok": False, "error": str(e)}
        _notify_offsite_sync_failure(result, str(e))
        return

    duration = round(time.time() - started, 3)
    if proc.returncode == 0:
        result["offsite_sync"] = {"ok": True, "duration_seconds": duration}
        logger.info(f"备份副本已推送（耗时 {duration}s）")
        return

    stderr_tail = (proc.stderr or "").strip()[-500:] or f"退出码 {proc.returncode}"
    logger.error(f"备份副本同步失败（退出码 {proc.returncode}）: {stderr_tail}")
    result["offsite_sync"] = {
        "ok": False, "returncode": proc.returncode, "duration_seconds": duration,
        "error": stderr_tail,
    }
    _notify_offsite_sync_failure(result, stderr_tail)


def run_backup(include_files: bool = None) -> dict:
    """Run one complete backup (database + optional material files).

    Arguments
    - include_files: whether to pack material files; None means use BACKUP_INCLUDE_FILES

    Returns a result summary:
    {"success", "db_backup", "files_backup", "manifest",
     "duration_seconds", "error", "cleaned", "offsite_sync"}

    Any failure in the database or file backup is only recorded in the result,
    never raised (a backup must not affect the business).
    """
    started = time.time()
    timestamp = _now().strftime(TIMESTAMP_FORMAT)
    dest_dir = get_backup_dir()
    if include_files is None:
        include_files = include_files_enabled()

    result = {
        "success": False,
        "timestamp": timestamp,
        "backup_dir": dest_dir,
        "db_backup": None,
        "files_backup": None,
        "manifest": None,
        "duration_seconds": 0.0,
        "error": None,
        "cleaned": [],
        "offsite_sync": None,
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

    # ---- 1) Database backup ----
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

    # ---- 2) Material file backup ----
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

    # ---- 3) Write the manifest (written on both success and failure, for troubleshooting and the "backed up today" check) ----
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

    # ---- 4) Marker file (lets the scheduler know whether "today was successfully backed up", avoiding duplicate runs within the hour) ----
    # Only written on success: on failure a retry chance is preserved (bounded by the
    # BACKUP_HOUR hour check, so same-day retries stay inside that hour window and never hammer)
    if result["success"]:
        try:
            with open(os.path.join(dest_dir, _MARKER_NAME), "w", encoding="utf-8") as f:
                f.write(_now().strftime("%Y-%m-%d"))
        except OSError as e:
            logger.warning(f"写入备份标记文件失败（不影响备份结果）: {e}")

    # ---- 5) Clean up old backups beyond the retention count ----
    try:
        result["cleaned"] = _cleanup_old(dest_dir, get_keep())
    except Exception as e:
        logger.warning(f"清理旧备份失败（不影响本次备份）: {e}")

    # ---- 6) Push a copy to another machine/disk (enabled once BACKUP_SYNC_CMD is set, off by default) ----
    # Backup dir and database share one host; if it dies both are lost — the biggest single
    # point of failure of single-host deployment. A sync failure does not overturn backup success, but alerts the admin.
    if result["success"]:
        try:
            _run_offsite_sync(result)
        except Exception as e:
            # Consistent with run_backup's "never raises" contract: a sync channel failure must not pierce the backup
            logger.error(f"副本推送执行异常: {e}", exc_info=True)
            result["offsite_sync"] = {"ok": False, "error": str(e)}

    if result["success"]:
        logger.info(
            f"备份完成: db={result['db_backup']} files={result['files_backup']} "
            f"耗时 {result['duration_seconds']}s"
        )
    else:
        logger.error(f"备份失败: {result['error']}")
        # Failures must be known: nobody reads logs proactively; alerts get things handled.
        # The alert call is also wrapped: run_backup's contract is "never raises", and a
        # broken alert channel must not pierce that contract.
        try:
            _notify_backup_failure(result)
        except Exception as e:
            logger.error(f"备份失败告警发送异常: {e}", exc_info=True)
    return result


# ---------------------------------------------------------------- queries / scheduling helpers
def list_backups() -> list:
    """List all backups (from manifests, newest first), for the admin API.

    Each element is a manifest's content plus an extra "manifest_file" field.
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
    """Most recent backup time (datetime); returns None when there is no record.

    With success_only=True (default) only successful backups count, for the
    scheduler's "already backed up today" check; failed records must not block
    same-day retries.
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
    """Date string (YYYY-MM-DD) of the most recent successful backup; returns None when there is no record.

    Prefers the marker file (written on success), falling back to scanning manifests
    for successful records.
    """
    marker = os.path.join(get_backup_dir(), _MARKER_NAME)
    if os.path.exists(marker):
        # If the marker file is unreadable, fall back to scanning manifests, without affecting the check
        with suppress(OSError):
            with open(marker, encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
    last = last_backup_time(success_only=True)
    return last.strftime("%Y-%m-%d") if last else None


def should_run_now(now: datetime = None) -> bool:
    """Scheduler check: whether the automatic backup should run now.

    Rule: backup enabled && current hour == BACKUP_HOUR && no successful backup today.
    Uses both the marker file and the latest successful manifest time to avoid hourly
    duplicate backups; failures write no marker, so same-day retries remain possible.
    """
    if not is_enabled():
        return False
    now = now or _now()
    if now.hour != get_hour():
        return False
    # Already successfully backed up today: do not run again (failures write no marker, so retries stay possible)
    return _last_success_date() != now.strftime("%Y-%m-%d")


if __name__ == "__main__":
    # Convenient for external cron: python tasks/backup.py
    # Run directly as a script, the script directory is backend/tasks and backend is not
    # on sys.path; add it manually, or imports like from database / storage will fail.
    import sys

    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    outcome = run_backup()
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    # Exit non-zero on failure for cron alerting (does not affect the in-scheduler call)
    raise SystemExit(0 if outcome["success"] else 1)
