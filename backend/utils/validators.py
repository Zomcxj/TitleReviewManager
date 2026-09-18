"""
数据校验工具

身份证号校验：18 位号码的最后一位是校验位，按 GB 11643-1999 的
ISO 7064:1983 MOD 11-2 算法计算。校验位错误说明号码录入有误，
在生产环境（真实客户数据）必须拦截，否则后续报送机构会因信息错误被退回。
"""
from datetime import datetime
from typing import Optional

# 加权因子与校验码映射（GB 11643-1999）
_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_CHECK_CODES = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]


def validate_id_number(id_number: str) -> Optional[str]:
    """
    校验 18 位身份证号，合法返回 None，非法返回错误说明。

    规则：
    - 18 位：校验位必须正确，出生日期必须合法
    - 15 位（老式）：仅校验纯数字与出生日期
    - 允许末位 x/X（会统一为大写）
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
    # 出生日期不能是未来，也不能早于 1900 年
    return 1900 <= birth.year <= datetime.now().year


def normalize_id_number(id_number: str) -> str:
    """统一格式：去空白、末位 X 大写"""
    return (id_number or "").strip().upper()


def validate_phone(phone: Optional[str]) -> Optional[str]:
    """校验手机号（可为空），非法返回错误说明"""
    if not phone:
        return None
    value = phone.strip().replace(" ", "").replace("-", "")
    if not value.isdigit() or len(value) != 11 or not value.startswith("1"):
        return "手机号格式不正确，应为 11 位数字"
    return None
