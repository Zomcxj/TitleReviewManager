"""
敏感字段脱敏

背景：客户资料含身份证号、手机号，属于个人敏感信息（PII）。业务场景中
经常需要把名单发给合作方/机构，但**不需要**完整证件号 —— 明文外发既无必要
也放大泄露风险。

脱敏规则（保持可辨识、不可还原）：
    身份证 110101198501011239 → 110101********1239（保留前 6 位地区 + 后 4 位）
    手机号  13800138001        → 138****8001
    姓名    陈明辉              → 陈**（保留姓氏）
    邮箱    zhangsan@a.com     → zh***@a.com
"""
from typing import Optional


def mask_id_number(value: Optional[str]) -> str:
    """身份证号脱敏：保留前 6 位与后 4 位。

    前 6 位是地区码（便于核对归属），后 4 位便于人工比对，中间出生日期打码。
    15 位老式号码按前 6 后 3 处理。
    """
    if not value:
        return ""
    v = value.strip()
    if len(v) == 18:
        return f"{v[:6]}{'*' * 8}{v[-4:]}"
    if len(v) == 15:
        return f"{v[:6]}{'*' * 6}{v[-3:]}"
    if len(v) > 6:
        return f"{v[:3]}{'*' * (len(v) - 6)}{v[-3:]}"
    return "*" * len(v)


def mask_phone(value: Optional[str]) -> str:
    """手机号脱敏：保留前 3 后 4（138****8001）"""
    if not value:
        return ""
    v = value.strip()
    if len(v) >= 11:
        return f"{v[:3]}{'*' * (len(v) - 7)}{v[-4:]}"
    if len(v) > 4:
        return f"{v[:2]}{'*' * (len(v) - 4)}{v[-2:]}"
    return "*" * len(v)


def mask_name(value: Optional[str]) -> str:
    """姓名脱敏：保留姓氏（陈明辉 → 陈**）"""
    if not value:
        return ""
    v = value.strip()
    if len(v) <= 1:
        return v
    return v[0] + "*" * (len(v) - 1)


def mask_email(value: Optional[str]) -> str:
    """邮箱脱敏：保留首字符与域名（zhangsan@a.com → z***@a.com）"""
    if not value or "@" not in value:
        return value or ""
    local, _, domain = value.partition("@")
    if not local:
        return value
    return f"{local[0]}***@{domain}"


def mask_id_number_keep_tail4(value: Optional[str]) -> str:
    """仅保留身份证后 4 位（用于"已存在"类提示，不暴露地区与生日）"""
    if not value:
        return ""
    v = value.strip()
    return f"****{v[-4:]}" if len(v) >= 4 else "****"


# ---------- 按角色的字段级脱敏 ----------

# 这些角色可以看到完整证件号/手机号（前提是数据归属允许）
FULL_ACCESS_ROLES = {"admin"}

# 客户归属校验：业务员看自己名下客户时可看完整信息（日常核对需要），
# 看他人客户时脱敏；审核员需要核对材料与证件是否一致，但不需要完整号码。
def should_mask_customer(user: dict, customer) -> bool:
    """判断当前用户查看该客户时是否应脱敏。

    规则：
    - admin：始终完整（管理职责）
    - salesman：仅自己名下客户完整（日常核对需要），他人客户脱敏
    - reviewer：一律脱敏（审核材料不需要完整证件号）
    - 其他/未登录：脱敏
    """
    role = (user or {}).get("role")
    if role in FULL_ACCESS_ROLES:
        return False
    if role == "salesman":
        uid = (user or {}).get("user_id") or (user or {}).get("id")
        owner = getattr(customer, "assigned_salesman_id", None)
        return owner != uid
    return True


def apply_customer_masking(data: dict, user: dict, customer) -> dict:
    """按角色对客户字典中的敏感字段脱敏（原地修改并返回）。

    脱敏字段：身份证号、手机号。其余字段（学历、单位等）不属于高敏感信息，保留。
    """
    if not should_mask_customer(user, customer):
        return data
    if data.get("id_number"):
        data["id_number"] = mask_id_number(data["id_number"])
    if data.get("phone"):
        data["phone"] = mask_phone(data["phone"])
    return data
