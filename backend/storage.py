"""
Storage abstraction layer — supports two backends: local filesystem and NAS (SMB).
Switch via the STORAGE_BACKEND=local|smb env var; production can configure a NAS path.
"""
import json
import logging
import os
import uuid
from contextlib import suppress
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_FILE_AUDIT_LOG = os.path.join(os.path.dirname(__file__), "file_audit.log")


def _log_file_action(action: str, path: str, detail: str = ""):
    """Append file operation to audit log."""
    try:
        entry = json.dumps({
            "time": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "path": path,
            "detail": detail,
        }, ensure_ascii=False)
        with open(_FILE_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception as e:
        # Audit log write failure must not interrupt the file operation, but it must leave a trace:
        # a silent pass breaks the audit chain without anyone knowing (compliance risk).
        logger.warning(f"文件审计日志写入失败（操作 {action} / {path}）: {e}")

# Configuration: injected via environment variables
# In SMB mode NAS_ROOT is "a share directory already mounted by the OS"; this layer only does
# normal file reads/writes, implementing no SMB protocol — hence no SMB_USER/SMB_PASS: credentials
# belong to the mount configuration (/etc/fstab, mount -t cifs, Docker bind mount), not the app.
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")  # local | smb
NAS_ROOT = os.getenv("NAS_ROOT", "")  # e.g. //192.168.1.100/share (must already be mounted)

# Local development root directory
LOCAL_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nas_data")

# ---------- Directory structure constants ----------
CATEGORY_MAP = {
    "身份证明": "1-身份证明",
    "学历学位": "2-学历学位",
    "职称证书": "3-职称证书",
    "聘用/劳动合同": "4-聘用劳动合同",
    "业绩成果": "5-业绩成果",
    "论文著作": "6-论文著作",
    "继续教育": "7-继续教育",
}


def get_storage_root() -> str:
    """Get the storage root directory"""
    if STORAGE_BACKEND == "smb" and NAS_ROOT:
        return NAS_ROOT
    os.makedirs(LOCAL_ROOT, exist_ok=True)
    return LOCAL_ROOT


def ensure_dir(path: str) -> str:
    full = os.path.join(get_storage_root(), path)
    os.makedirs(full, exist_ok=True)
    return full


def customer_dir(year: int, salesman_name: str, customer_name: str, initial: str = "") -> str:
    """Build the customer directory path: customers/{year}/{salesman_name}/{customer_name}_{initial}/"""
    salesman_dir = salesman_name or "未分配"
    name_part = f"{customer_name}_{initial}" if initial else customer_name
    return f"customers/{year}/{salesman_dir}/{name_part}"


def category_subdir(customer_rel: str, category: str) -> str:
    """Build the material category subdirectory"""
    cat_dir = CATEGORY_MAP.get(category, category)
    return os.path.join(customer_rel, cat_dir)


def create_customer_directories(year: int, salesman_name: str, customer_name: str, initial: str = "") -> str:
    """Create the full directory template when a new customer is added"""
    base = customer_dir(year, salesman_name, customer_name, initial)
    root = get_storage_root()
    full = os.path.join(root, base)
    logger.info(f"Creating customer directories at: {full}")
    for cat_path in CATEGORY_MAP.values():
        ensure_dir(os.path.join(base, cat_path))
    logger.info(f"Created customer directories: {base} (root={root})")
    return base


def rename_customer_directory(old_rel: str, new_rel: str) -> bool:
    """Rename the directory on customer rename/salesman reassignment (customers.py transfer/rename sync depends on this)"""
    root = get_storage_root()
    old_path = os.path.join(root, old_rel)
    new_path = os.path.join(root, new_rel)
    if not os.path.exists(old_path):
        return False
    try:
        os.renames(old_path, new_path)
        return True
    except Exception as e:
        logger.error(f"Rename dir failed: {e}")
        return False


def _resolve_new_path(customer_rel: str, category: str, filename: str) -> tuple[str, str, str]:
    """Shared naming logic for save_file / save_file_from_fileobj.

    Returns (sub, safe_name, full_path); auto-suffixes when a file with the same
    name already exists, so concurrent saves never overwrite each other.
    """
    safe_name = _sanitize_filename(filename)
    sub = category_subdir(customer_rel, category)
    ensure_dir(sub)
    full_path = os.path.join(get_storage_root(), sub, safe_name)
    if os.path.exists(full_path):
        name, ext = os.path.splitext(safe_name)
        safe_name = f"{name}_{uuid.uuid4().hex[:4]}{ext}"
        full_path = os.path.join(get_storage_root(), sub, safe_name)
    return sub, safe_name, full_path


def save_file(customer_rel: str, category: str, filename: str, content: bytes) -> str:
    """
    Save a file under the customer directory, keeping the original filename.
    Returns the relative path (relative to the storage root).

    For large uploads prefer save_file_from_fileobj: it writes in chunks so peak
    memory stays at one chunk instead of the whole file.
    """
    sub, safe_name, full_path = _resolve_new_path(customer_rel, category, filename)
    with open(full_path, "wb") as f:
        f.write(content)
    rel_path = os.path.join(sub, safe_name).replace("\\", "/")
    _log_file_action("CREATE", rel_path, f"category={category}, size={len(content)}")
    logger.info(f"File saved: {rel_path} ({len(content)} bytes)")
    return rel_path


SAVE_CHUNK_SIZE = 1024 * 1024  # 1MB: peak memory per upload stays at one chunk


def save_file_from_fileobj(
    customer_rel: str, category: str, filename: str, fileobj, max_bytes: int | None = None
) -> tuple[str, int]:
    """Stream a binary file object to the customer directory in chunks.

    Unlike save_file(content), this never holds the whole file in memory —
    peak allocation is SAVE_CHUNK_SIZE regardless of file size. Reads via
    fileobj.read(SAVE_CHUNK_SIZE); stops (and deletes the partial file) when
    max_bytes is exceeded. Returns (relative_path, bytes_written).
    """
    sub, safe_name, full_path = _resolve_new_path(customer_rel, category, filename)
    written = 0
    try:
        with open(full_path, "wb") as f:
            while True:
                chunk = fileobj.read(SAVE_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise ValueError(f"file exceeds {max_bytes} bytes")
                f.write(chunk)
    except Exception:
        # A truncated file on disk is worse than no file: clean up on any failure
        with suppress(OSError):
            os.remove(full_path)
        raise
    rel_path = os.path.join(sub, safe_name).replace("\\", "/")
    _log_file_action("CREATE", rel_path, f"category={category}, size={written}")
    logger.info(f"File saved: {rel_path} ({written} bytes)")
    return rel_path, written


def open_file(rel_path: str):
    """Open a storage file for streaming reads; caller must close it.

    Rejects paths escaping the storage root like read_file; returns None when
    unsafe or missing. Lets callers (e.g. batch zip download) copy in chunks
    instead of loading whole files into memory.
    """
    from utils.upload_guard import is_safe_relative_path
    if not is_safe_relative_path(rel_path):
        logger.warning(f"拒绝越界路径读取: {rel_path}")
        return None
    full = os.path.join(get_storage_root(), rel_path)
    if not os.path.exists(full):
        return None
    return open(full, "rb")


def full_path(rel_path: str) -> str | None:
    """Validated absolute path inside the storage root (None when unsafe/missing).

    For handing to FileResponse so downloads stream from disk instead of
    materialising the whole file in memory.
    """
    from utils.upload_guard import is_safe_relative_path
    if not is_safe_relative_path(rel_path):
        logger.warning(f"拒绝越界路径读取: {rel_path}")
        return None
    full = os.path.join(get_storage_root(), rel_path)
    return full if os.path.exists(full) else None


def read_file(rel_path: str) -> bytes | None:
    """Read a whole file into memory (rejects paths escaping the storage root).

    Only for small files. For user-material sized files use open_file() or
    full_path() + FileResponse — materialising a 50MB upload as one bytes
    object is exactly the kind of avoidable memory spike this module avoids.
    """
    from utils.upload_guard import is_safe_relative_path
    if not is_safe_relative_path(rel_path):
        logger.warning(f"拒绝越界路径读取: {rel_path}")
        return None
    full = os.path.join(get_storage_root(), rel_path)
    if not os.path.exists(full):
        return None
    with open(full, "rb") as f:
        return f.read()


def delete_file(rel_path: str) -> bool:
    """Delete a file (rejects relative paths escaping the storage root)"""
    from utils.upload_guard import is_safe_relative_path
    if not is_safe_relative_path(rel_path):
        logger.warning(f"拒绝越界路径删除: {rel_path}")
        _log_file_action("DELETE_REJECTED", rel_path, "unsafe path")
        return False
    full = os.path.join(get_storage_root(), rel_path)
    if os.path.exists(full):
        os.remove(full)
        _log_file_action("DELETE", rel_path)
        return True
    _log_file_action("DELETE_FAILED", rel_path, "file not found")
    return False


def list_files(customer_rel: str) -> list[dict]:
    """
    Walk the customer directory and return a file tree.
    Return structure:
    [
        {"category": "<category dir name>", "files": [{"name": "...", "path": "...", "size": 123, "modified": "..."}]},
        ...
    ]
    """
    root = get_storage_root()
    base = os.path.join(root, customer_rel)
    if not os.path.exists(base):
        return []
    result = []
    for entry in sorted(os.listdir(base)):
        entry_path = os.path.join(base, entry)
        if not os.path.isdir(entry_path):
            continue
        files = []
        for fname in sorted(os.listdir(entry_path)):
            fpath = os.path.join(entry_path, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "name": fname,
                    "path": os.path.join(customer_rel, entry, fname).replace("\\", "/"),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        if files:
            result.append({"category": entry, "files": files})
    return result


def _sanitize_filename(name: str) -> str:
    """Sanitize a filename: strip path info, block directory traversal, limit length (see utils/upload_guard.safe_filename)"""
    from utils.upload_guard import safe_filename
    return safe_filename(name, fallback="file")


# ---------- Pinyin initial utility (based on GB2312 encoding ranges; common hanzi sorted by pinyin) ----------
def get_pinyin_initial(name: str) -> str:
    """
    Get the pinyin initials of a name (uppercase).
    Leverages the fact that level-1 GB2312 hanzi are sorted by pinyin: encode the character
    as GB2312, then map its double-byte code range to A-Z.
    """
    if not name:
        return ""
    initials = []
    for char in name:
        if '\u4e00' <= char <= '\u9fff':
            initial = _char_to_initial(char)
            if initial:
                initials.append(initial)
        elif 'a' <= char.lower() <= 'z':
            initials.append(char.upper())
    return "".join(initials[:4])  # take at most 4 initials


# Double-byte code ranges of level-1 GB2312 hanzi (pinyin-sorted) -> initial letter
_GB2312_PINYIN_RANGES = [
    (0xB0A1, 0xB0C4, 'A'), (0xB0C5, 0xB2C0, 'B'), (0xB2C1, 0xB4ED, 'C'),
    (0xB4EE, 0xB6E9, 'D'), (0xB6EA, 0xB7A1, 'E'), (0xB7A2, 0xB8C0, 'F'),
    (0xB8C1, 0xB9FD, 'G'), (0xB9FE, 0xBBF6, 'H'), (0xBBF7, 0xBFA5, 'J'),
    (0xBFA6, 0xC0AB, 'K'), (0xC0AC, 0xC2E7, 'L'), (0xC2E8, 0xC4C2, 'M'),
    (0xC4C3, 0xC5B5, 'N'), (0xC5B6, 0xC5BD, 'O'), (0xC5BE, 0xC6D9, 'P'),
    (0xC6DA, 0xC8BA, 'Q'), (0xC8BB, 0xC8F5, 'R'), (0xC8F6, 0xCBF9, 'S'),
    (0xCBFA, 0xCDD9, 'T'), (0xCDDA, 0xCEF3, 'W'), (0xCEF4, 0xD188, 'X'),
    (0xD189, 0xD4D0, 'Y'), (0xD4D1, 0xD7F9, 'Z'),
]


def _char_to_initial(char: str) -> str | None:
    """Hanzi -> pinyin initial; returns None for rare characters outside GB2312"""
    try:
        code = int.from_bytes(char.encode("gb2312"), "big")
    except (UnicodeEncodeError, OverflowError):
        return None
    for start, end, letter in _GB2312_PINYIN_RANGES:
        if start <= code <= end:
            return letter
    return None
