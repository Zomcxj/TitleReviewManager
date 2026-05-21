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
    for cat_path in CATEGORY_MAP.values():
        ensure_dir(os.path.join(base, cat_path))
    logger.info(f"Created customer directories: {base}")
    return base


def rename_customer_directory(old_rel: str, new_rel: str) -> bool:
    """客户改名/调换业务员时重命名目录"""
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


# ---------- 拼音首字母工具（简单实现，无需额外库） ----------
def get_pinyin_initial(name: str) -> str:
    """
    获取姓名拼音首字母（大写）。
    简单实现：取姓名的拼音首字母。
    为简化，这里取每个汉字 Unicode 区间映射的首字母。
    更精确需要 pypinyin 库。
    """
    if not name:
        return ""
    initials = []
    for char in name:
        if '\u4e00' <= char <= '\u9fff':
            initials.append(_char_to_initial(char))
        elif 'a' <= char.lower() <= 'z':
            initials.append(char.upper())
    return "".join(initials[:4])  # 最多取4个首字母


def _char_to_initial(char: str) -> str:
    """汉字 -> 拼音首字母（近似映射）"""
    code = ord(char)
    # Unicode 拼音首字母区间映射
    ranges = [
        (0x4E00, 0x4EAC, 'A'), (0x4EAD, 0x4FBB, 'B'), (0x4FBC, 0x5000, 'C'),
        (0x5001, 0x506C, 'D'), (0x506D, 0x50DA, 'E'), (0x50DB, 0x51A0, 'F'),
        (0x51A1, 0x5265, 'G'), (0x5266, 0x5314, 'H'), (0x5315, 0x5348, 'I'),
        (0x5349, 0x53D1, 'J'), (0x53D2, 0x5450, 'K'), (0x5451, 0x5583, 'L'),
        (0x5584, 0x56A5, 'M'), (0x56A6, 0x56D7, 'N'), (0x56D8, 0x5705, 'O'),
        (0x5706, 0x57F0, 'P'), (0x57F1, 0x58EE, 'Q'), (0x58EF, 0x5A00, 'R'),
        (0x5A01, 0x5B00, 'S'), (0x5B01, 0x5C00, 'T'), (0x5C01, 0x5CFF, 'W'),
        (0x5D00, 0x5DFF, 'X'), (0x5E00, 0x5EFF, 'Y'), (0x5F00, 0x9FFF, 'Z'),
    ]
    for start, end, letter in ranges:
        if start <= code <= end:
            return letter
    return 'Z'
