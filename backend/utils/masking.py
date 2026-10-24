"""
Sensitive field masking

Background: customer profiles contain ID numbers and phone numbers — personal
sensitive information (PII). Business scenarios often require sending rosters to
partners/agencies, but the **full** ID number is not needed — sending it in plain
text is both unnecessary and amplifies leak risk.

Masking rules (recognizable, but not reversible):
    ID number  110101198501011239 -> 110101********1239 (keep first 6 region digits + last 4)
    Phone      13800138001        -> 138****8001
    Name       Chen Minghui       -> Chen** (keep surname)
    Email      zhangsan@a.com     -> zh***@a.com
"""


def mask_id_number(value: str | None) -> str:
    """Mask an ID number: keep the first 6 and last 4 digits.

    The first 6 digits are the region code (handy for verifying ownership) and the
    last 4 aid manual comparison; the birth date in the middle is masked.
    Legacy 15-digit numbers keep the first 6 and last 3.
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


def mask_phone(value: str | None) -> str:
    """Mask a phone number: keep the first 3 and last 4 digits (138****8001)"""
    if not value:
        return ""
    v = value.strip()
    if len(v) >= 11:
        return f"{v[:3]}{'*' * (len(v) - 7)}{v[-4:]}"
    if len(v) > 4:
        return f"{v[:2]}{'*' * (len(v) - 4)}{v[-2:]}"
    return "*" * len(v)


# ---------- Role-based field-level masking ----------

# Roles allowed to see full ID numbers/phone numbers (provided data ownership permits)
FULL_ACCESS_ROLES = {"admin"}

# Ownership check: a salesman may see full info for their own customers (daily
# verification); masked for others' customers; reviewers compare materials vs IDs but need no full numbers.
def should_mask_customer(user: dict, customer) -> bool:
    """Decide whether to mask this customer for the current user.

    Rules:
    - admin: always full (management duty)
    - salesman: full only for their own customers (daily verification), masked for others'
    - reviewer: always masked (reviewing materials does not need full ID numbers)
    - other/unauthenticated: masked
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
    """Mask sensitive fields in a customer dict by role (modifies in place and returns).

    Masked fields: ID number, phone number. Other fields (education, employer, etc.)
    are not highly sensitive and are kept.
    """
    if not should_mask_customer(user, customer):
        return data
    if data.get("id_number"):
        data["id_number"] = mask_id_number(data["id_number"])
    if data.get("phone"):
        data["phone"] = mask_phone(data["phone"])
    return data
