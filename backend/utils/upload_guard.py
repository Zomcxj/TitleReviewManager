"""
上传文件内容校验与文件名安全处理

为什么需要魔数校验：
    仅校验扩展名时，攻击者可以把 .html/.svg/.exe 改名为 .pdf 上传。
    虽然下载接口强制 `application/octet-stream` + attachment，能挡住直接执行，
    但文件会被存进 NAS 并可能被其他系统（如运维直接打开目录）消费。
    校验真实文件头是更稳妥的一层。

为什么需要文件名净化加固：
    `_sanitize_filename` 只替换了 Windows 非法字符，未处理 `..` 与绝对路径。
    文件名来自客户端，`../../etc/passwd` 这类输入必须拦截。
"""
import os

# 各扩展名允许的文件头（magic bytes）
# 说明：docx/xlsx 等 OOXML 是 zip 容器，文件头为 PK\x03\x04；
# 老式 .doc 是 OLE 复合文档，头为 D0 CF 11 E0。
_MAGIC_PREFIXES = {
    ".pdf": [b"%PDF"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".docx": [b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"],
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04"],
}

# 单文件最多读取多少字节用于判断（避免大文件全读）
_HEADER_READ_BYTES = 16


def validate_file_content(filename: str, content: bytes) -> str | None:
    """按扩展名校验文件真实内容，合法返回 None，非法返回中文原因。

    未知扩展名（不在白名单映射中）不做内容校验，由扩展名白名单负责拦截。
    """
    ext = os.path.splitext(filename or "")[1].lower()
    expected = _MAGIC_PREFIXES.get(ext)
    if not expected:
        return None

    head = content[:_HEADER_READ_BYTES]
    if not head:
        return "文件内容为空"

    if any(head.startswith(prefix) for prefix in expected):
        return None

    readable = ext.lstrip(".").upper()
    return (
        f"文件内容与扩展名 {readable} 不符，可能不是真实文件。"
        f"请确认文件未损坏、未被改扩展名后重新上传"
    )


def safe_filename(name: str, fallback: str = "file") -> str:
    """文件名净化加固：去掉路径部分、阻断目录穿越、限制长度。

    与 storage._sanitize_filename 的区别：本函数额外处理
    - 路径分隔符（含 Windows 反斜杠）
    - `..` 与 `.` 这类特殊名
    - 绝对路径与盘符
    - 前后空白与末尾点号（Windows 下会被静默截断）
    """
    if not name:
        return fallback

    # 1. 只取最后一段（同时处理 / 与 \），彻底去掉路径信息
    name = name.replace("\\", "/").split("/")[-1]

    # 2. 去掉控制字符与常见非法字符
    illegal = '<>:"/\\|?*'
    cleaned = "".join(("_" if (ch in illegal or ord(ch) < 32) else ch) for ch in name)

    # 3. 处理纯点号名与前后点号/空白
    cleaned = cleaned.strip().strip(".")
    if cleaned in ("", ".", ".."):
        return fallback

    # 4. 限制长度（保留扩展名），避免超出数据库字段与文件系统限制
    max_len = 200
    if len(cleaned) > max_len:
        stem, ext = os.path.splitext(cleaned)
        cleaned = stem[: max_len - len(ext)] + ext

    return cleaned or fallback


def is_safe_relative_path(rel_path: str) -> bool:
    """校验相对路径未越出存储根目录（用于读取/删除已存储文件时的兜底检查）"""
    if not rel_path:
        return False
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0]:
        return False  # 绝对路径或盘符
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    # 含 .. 说明试图越出存储根目录
    return not any(p == ".." for p in parts)
