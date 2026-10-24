"""
Unified enum and constant definitions

This module centrally manages all enum types and constants in the project, avoiding
duplicate definitions in models.py and schemas.py.
"""

from enum import Enum


class ApplicationStatus(str, Enum):
    """Application (batch) statuses"""
    INITIAL = "初次申报"
    SUPPLEMENT = "资料补充"
    COMPLETED = "完成资料"
    SUBMITTED = "提交评审机构审核"
    REVISE = "返修"
    APPROVED = "通过"
    REJECTED = "不通过"
    REAPPLY = "二次申报"


class MaterialCategory(str, Enum):
    """Material categories"""
    IDENTITY = "身份证明"
    EDUCATION = "学历学位"
    TITLE_CERT = "职称证书"
    EMPLOYMENT_CONTRACT = "聘用/劳动合同"
    ACHIEVEMENTS = "业绩成果"
    PUBLICATIONS = "论文著作"
    CONTINUING_EDUCATION = "继续教育"


class AuditStatus(str, Enum):
    """Material review statuses"""
    PENDING = "待审核"
    PASSED = "已通过"
    FLAGGED = "已标记问题"


class FeedbackType(str, Enum):
    """Agency feedback types"""
    APPROVED = "通过"
    REJECTED = "不通过"
    REVISE = "返修"


# Status transition rules: key = current status, value = list of allowed next statuses
VALID_TRANSITIONS = {
    ApplicationStatus.INITIAL: [ApplicationStatus.SUPPLEMENT, ApplicationStatus.COMPLETED],
    ApplicationStatus.SUPPLEMENT: [ApplicationStatus.COMPLETED],
    ApplicationStatus.COMPLETED: [ApplicationStatus.SUBMITTED],
    ApplicationStatus.SUBMITTED: [ApplicationStatus.REVISE, ApplicationStatus.APPROVED, ApplicationStatus.REJECTED],
    ApplicationStatus.REVISE: [ApplicationStatus.SUPPLEMENT, ApplicationStatus.COMPLETED],
    ApplicationStatus.REJECTED: [ApplicationStatus.REAPPLY],
    ApplicationStatus.REAPPLY: [ApplicationStatus.SUPPLEMENT, ApplicationStatus.COMPLETED],
    ApplicationStatus.APPROVED: [],  # terminal state
}

# File upload config (materials / reviews / feedback all import from enums)
ALLOWED_FILE_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


class PaymentStatus(str, Enum):
    """Payment/receivable statuses"""
    UNPAID = "未收费"
    PARTIAL = "部分收费"
    PAID = "已结清"
    REFUNDED = "已退款"


class CertificateStatus(str, Enum):
    """Certificate issuance statuses"""
    NOT_ISSUED = "未发证"
    ISSUED = "已发证"
    DELIVERED = "已交付"


class CustomerSource(str, Enum):
    """Customer source channels"""
    REFERRAL = "老客户转介绍"
    ONLINE = "网络渠道"
    OFFLINE = "线下推广"
    PARTNER = "合作机构"
    SELF = "客户自助注册"
    OTHER = "其他"


# ---------- Required application materials (per professional category, validated before submitting to the review agency) ----------
# Common required materials: every application must have them
REQUIRED_MATERIALS_COMMON = [
    MaterialCategory.IDENTITY.value,
    MaterialCategory.EDUCATION.value,
    MaterialCategory.EMPLOYMENT_CONTRACT.value,
]

# Extra required materials per professional category (key is a category keyword; a match adds the requirement)
REQUIRED_MATERIALS_BY_CATEGORY = {
    "工程": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
    "建筑": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
    "土木": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
    "电子": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
    "材料": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
    "教育": [MaterialCategory.TITLE_CERT.value, MaterialCategory.PUBLICATIONS.value],
    "教学": [MaterialCategory.TITLE_CERT.value, MaterialCategory.PUBLICATIONS.value],
    "卫生": [MaterialCategory.TITLE_CERT.value, MaterialCategory.CONTINUING_EDUCATION.value],
    "医疗": [MaterialCategory.TITLE_CERT.value, MaterialCategory.CONTINUING_EDUCATION.value],
    "环境": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
    "道路": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
    "桥梁": [MaterialCategory.TITLE_CERT.value, MaterialCategory.ACHIEVEMENTS.value],
}


def required_materials_for(professional_category: str = "") -> list[str]:
    """Return the list of required material categories for an application in a given professional category (deduplicated, stable order)"""
    required = list(REQUIRED_MATERIALS_COMMON)
    cat = professional_category or ""
    for keyword, extra in REQUIRED_MATERIALS_BY_CATEGORY.items():
        if keyword in cat:
            for c in extra:
                if c not in required:
                    required.append(c)
    return required


# ---------- System config defaults (overridable via the SystemConfig table, adjustable online by admins) ----------
DEFAULT_SYSTEM_CONFIG = {
    "pool_claim_limit": 50,            # max customers a single salesman can hold
    "pool_recovery_days": 7,           # days without follow-up before auto-reclaim
    "sla_hours_after_assign": 24,      # SLA hours after assignment
    "sla_hours_before_review": 48,     # SLA hours while pending review
    "max_file_size_mb": 50,            # per-file size limit (MB)
    "login_lockout_threshold": 10,     # consecutive login failures before lockout
    "login_lockout_minutes": 15,       # lockout duration (minutes)
    "reject_duplicate_phone": 0,       # whether to reject duplicate phone numbers (1/0)
}

SYSTEM_CONFIG_LABELS = {
    "pool_claim_limit": "业务员持有客户上限",
    "pool_recovery_days": "无跟进自动回收天数",
    "sla_hours_after_assign": "分配后 SLA 小时",
    "sla_hours_before_review": "待审核 SLA 小时",
    "max_file_size_mb": "单文件大小上限(MB)",
    "login_lockout_threshold": "登录失败锁定阈值",
    "login_lockout_minutes": "账号锁定时长(分钟)",
    "reject_duplicate_phone": "拒绝重复手机号(1/0)",
}
