"""
Data validation utilities

ID number validation: the last digit of an 18-digit number is a check digit computed
with the ISO 7064:1983 MOD 11-2 algorithm from GB 11643-1999. A wrong check digit
means the number was entered incorrectly and must be rejected in production (real
customer data), otherwise the agency will return the submission over wrong information.
"""
from datetime import datetime

# Weighting factors and check-code mapping (GB 11643-1999)
_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_CHECK_CODES = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]


def validate_id_number(id_number: str) -> str | None:
    """
    Validate an 18-digit ID number; returns None if valid, an error message if not.

    Rules:
    - 18 digits: check digit must be correct, birth date must be valid
    - 15 digits (legacy): only digits-only and birth date are checked
    - A trailing x/X is allowed (normalized to uppercase)
    """
    if not id_number:
        return "身份证号不能为空"

    value = id_number.strip().upper()

    if len(value) == 15:
        if not value.isdigit():
            return "15 位身份证号必须全部为数字"
        if not _valid_birthdate(value[6:12], "%y%m%d"):
            return "身份证号中的出生日期不合法"
        return None

    if len(value) != 18:
        return "身份证号必须为 18 位（或 15 位老式号码）"

    if not value[:17].isdigit():
        return "身份证号前 17 位必须为数字"

    if value[17] not in "0123456789X":
        return "身份证号末位只能是数字或 X"

    if not _valid_birthdate(value[6:14], "%Y%m%d"):
        return "身份证号中的出生日期不合法"

    total = sum(int(value[i]) * _WEIGHTS[i] for i in range(17))
    if _CHECK_CODES[total % 11] != value[17]:
        return "身份证号校验位不正确，请核对后重新输入"

    return None


def _valid_birthdate(raw: str, fmt: str) -> bool:
    try:
        birth = datetime.strptime(raw, fmt)
    except ValueError:
        return False
    # Birth date must not be in the future, nor earlier than 1900
    return 1900 <= birth.year <= datetime.now().year


def normalize_id_number(id_number: str) -> str:
    """Normalize format: strip whitespace, uppercase a trailing X"""
    return (id_number or "").strip().upper()


def validate_phone(phone: str | None) -> str | None:
    """Validate a phone number (may be empty); returns an error message if invalid"""
    if not phone:
        return None
    value = phone.strip().replace(" ", "").replace("-", "")
    if not value.isdigit() or len(value) != 11 or not value.startswith("1"):
        return "手机号格式不正确，应为 11 位数字"
    return None


# ---------- Password strength ----------
# Common weak passwords (including the seed accounts' defaults) — must be rejected in production
WEAK_PASSWORDS = {
    "admin123", "sales123", "review123", "password", "123456", "12345678",
    "qwerty", "abc123", "111111", "000000", "admin", "root", "test123",
    "password123", "changeme", "letmein", "welcome",
}


def check_password_strength(password: str, min_length: int = 8) -> str | None:
    """Check password strength; returns None if acceptable, a Chinese reason otherwise.

    Rules (reasonable strength for an internal management system):
    - Length >= min_length (default 8)
    - Must not be a common weak password
    - Must not be digits-only or letters-only
    - Must not equal the username or contain it
    """
    if not password:
        return "密码不能为空"
    if len(password) < min_length:
        return f"密码长度至少 {min_length} 位"
    if password.lower() in WEAK_PASSWORDS:
        return "该密码过于常见，请使用更复杂的密码"
    if password.isdigit():
        return "密码不能为纯数字"
    if password.isalpha():
        return "密码不能为纯字母"
    return None


