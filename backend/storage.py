"""
存储抽象层 —— 支持本地文件系统和 NAS（SMB）两种后端。
通过环境变量 STORAGE_BACKEND=local|smb 切换，生产环境可配 NAS 路径。
"""
import os, shutil, uuid, logging, json
from typing import Optional, List, Dict
from pathlib import Path
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
    except Exception:
        pass

# 配置：通过环境变量注入
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")  # local | smb
NAS_ROOT = os.getenv("NAS_ROOT", "")  # e.g. //192.168.1.100/share
SMB_USER = os.getenv("SMB_USER", "")
SMB_PASS = os.getenv("SMB_PASS", "")

# 本地开发模式根目录
LOCAL_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nas_data")

# ---------- 目录结构常量 ----------
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
    """获取存储根目录"""
    if STORAGE_BACKEND == "smb" and NAS_ROOT:
        return NAS_ROOT
    os.makedirs(LOCAL_ROOT, exist_ok=True)
    return LOCAL_ROOT


def ensure_dir(path: str) -> str:
    full = os.path.join(get_storage_root(), path)
    os.makedirs(full, exist_ok=True)
    return full


def customer_dir(year: int, salesman_name: str, customer_name: str, initial: str = "") -> str:
    """生成客户目录路径: customers/{year}/{salesman_name}/{customer_name}_{initial}/"""
    salesman_dir = salesman_name or "未分配"
    name_part = f"{customer_name}_{initial}" if initial else customer_name
    return f"customers/{year}/{salesman_dir}/{name_part}"


def category_subdir(customer_rel: str, category: str) -> str:
    """生成材料类别子目录"""
    cat_dir = CATEGORY_MAP.get(category, category)
    return os.path.join(customer_rel, cat_dir)


def create_customer_directories(year: int, salesman_name: str, customer_name: str, initial: str = "") -> str:
    """新建客户时创建完整目录模板"""
    base = customer_dir(year, salesman_name, customer_name, initial)
    root = get_storage_root()
    full = os.path.join(root, base)
    logger.info(f"Creating customer directories at: {full}")
    for cat_path in CATEGORY_MAP.values():
        ensure_dir(os.path.join(base, cat_path))
    logger.info(f"Created customer directories: {base} (root={root})")
    return base


def rename_customer_directory(old_rel: str, new_rel: str) -> bool:
    """客户改名/调换业务员时重命名目录（customers.py 的转让/改名同步依赖此函数）"""
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


def save_file(customer_rel: str, category: str, filename: str, content: bytes) -> str:
    """
    保存文件到客户目录下，保留原始文件名。
    返回相对路径（相对于存储根目录）。
    """
    safe_name = _sanitize_filename(filename)
    sub = category_subdir(customer_rel, category)
    ensure_dir(sub)
    full_path = os.path.join(get_storage_root(), sub, safe_name)
    # 同名文件自动加后缀
    if os.path.exists(full_path):
        name, ext = os.path.splitext(safe_name)
        safe_name = f"{name}_{uuid.uuid4().hex[:4]}{ext}"
        full_path = os.path.join(get_storage_root(), sub, safe_name)
    with open(full_path, "wb") as f:
        f.write(content)
    rel_path = os.path.join(sub, safe_name).replace("\\", "/")
    _log_file_action("CREATE", rel_path, f"category={category}, size={len(content)}")
    logger.info(f"File saved: {rel_path} ({len(content)} bytes)")
    return rel_path


def read_file(rel_path: str) -> Optional[bytes]:
    """读取文件"""
    full = os.path.join(get_storage_root(), rel_path)
    if not os.path.exists(full):
        return None
    with open(full, "rb") as f:
        return f.read()


def delete_file(rel_path: str) -> bool:
    """删除文件"""
    full = os.path.join(get_storage_root(), rel_path)
    if os.path.exists(full):
        os.remove(full)
        _log_file_action("DELETE", rel_path)
        return True
    _log_file_action("DELETE_FAILED", rel_path, "file not found")
    return False


def list_files(customer_rel: str) -> List[Dict]:
    """
    遍历客户目录，返回文件树。
    返回结构:
    [
        {"category": "1-身份证明", "files": [{"name": "...", "path": "...", "size": 123, "modified": "..."}]},
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
    """清理文件名中的非法字符"""
    illegal = r'<>:"/\|?*'
    for ch in illegal:
        name = name.replace(ch, "_")
    return name


# ---------- 拼音首字母工具（基于 GB2312 编码区间，常用汉字按拼音排序） ----------
def get_pinyin_initial(name: str) -> str:
    """
    获取姓名拼音首字母（大写）。
    利用 GB2312 一级汉字按拼音排序的特性：将汉字编码为 GB2312 后，
    按双字节编码区间映射到 A-Z。
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
    return "".join(initials[:4])  # 最多取4个首字母


# GB2312 一级汉字（按拼音排序）的双字节编码区间 -> 首字母
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


def _char_to_initial(char: str) -> Optional[str]:
    """汉字 -> 拼音首字母；GB2312 之外的生僻字返回 None"""
    try:
        code = int.from_bytes(char.encode("gb2312"), "big")
    except (UnicodeEncodeError, OverflowError):
        return None
    for start, end, letter in _GB2312_PINYIN_RANGES:
        if start <= code <= end:
            return letter
    return None
