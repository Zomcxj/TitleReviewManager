"""
Upload content validation and filename hardening

Why magic-number validation is needed:
    With extension-only checks, an attacker can rename .html/.svg/.exe to .pdf and
    upload. The download endpoint forces `application/octet-stream` + attachment,
    which blocks direct execution, but the file still lands on the NAS and may be
    consumed by other systems (e.g. ops browsing the directory). Verifying the real
    file header is a more solid layer.

Why filename sanitization hardening is needed:
    `_sanitize_filename` only replaced Windows-illegal characters and did not handle
    `..` or absolute paths. Filenames come from the client; inputs like
    `../../etc/passwd` must be intercepted.
"""
import os

# Allowed file headers (magic bytes) per extension
# Note: docx/xlsx and other OOXML are zip containers with the PK\x03\x04 header;
# legacy .doc is an OLE compound document with the D0 CF 11 E0 header.
_MAGIC_PREFIXES = {
    ".pdf": [b"%PDF"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".docx": [b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"],
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04"],
}

# Max bytes read per file for the check (avoids reading large files entirely)
_HEADER_READ_BYTES = 16


def validate_file_content(filename: str, content: bytes) -> str | None:
    """Validate the file's real content against its extension; returns None if valid, a Chinese error reason if not.

    Unknown extensions (not in the mapping) skip content validation; the extension
    whitelist is responsible for blocking those.
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
    """Filename sanitization hardening: strip path parts, block directory traversal, limit length.

    Differences from storage._sanitize_filename: this function additionally handles
    - path separators (including Windows backslashes)
    - special names like `..` and `.`
    - absolute paths and drive letters
    - surrounding whitespace and trailing dots (silently truncated on Windows)
    """
    if not name:
        return fallback

    # 1. Keep only the last segment (handles both / and \), removing all path information
    name = name.replace("\\", "/").split("/")[-1]

    # 2. Remove control characters and common illegal characters
    illegal = '<>:"/\\|?*'
    cleaned = "".join(("_" if (ch in illegal or ord(ch) < 32) else ch) for ch in name)

    # 3. Handle dot-only names plus surrounding dots/whitespace
    cleaned = cleaned.strip().strip(".")
    if cleaned in ("", ".", ".."):
        return fallback

    # 4. Limit length (keeping the extension) to fit database columns and filesystem limits
    max_len = 200
    if len(cleaned) > max_len:
        stem, ext = os.path.splitext(cleaned)
        cleaned = stem[: max_len - len(ext)] + ext

    return cleaned or fallback


def is_safe_relative_path(rel_path: str) -> bool:
    """Verify a relative path stays inside the storage root (final safeguard when reading/deleting stored files)"""
    if not rel_path:
        return False
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0]:
        return False  # absolute path or drive letter
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    # A ".." segment means an attempt to escape the storage root
    return not any(p == ".." for p in parts)
