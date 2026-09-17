"""
统一的枚举和常量定义

本模块集中管理项目中所有枚举类型和常量，避免在 models.py 和 schemas.py 中重复定义。
"""

from enum import Enum


class UserRole(str, Enum):
    """用户角色"""
    ADMIN = "admin"
    SALESMAN = "salesman"
    REVIEWER = "reviewer"


class ApplicationStatus(str, Enum):
    """申报批次状态"""
    INITIAL = "初次申报"
    SUPPLEMENT = "资料补充"
    COMPLETED = "完成资料"
    SUBMITTED = "提交评审机构审核"
    REVISE = "返修"
    APPROVED = "通过"
    REJECTED = "不通过"
    REAPPLY = "二次申报"


class MaterialCategory(str, Enum):
    """材料类别"""
    IDENTITY = "身份证明"
    EDUCATION = "学历学位"
    TITLE_CERT = "职称证书"
    EMPLOYMENT_CONTRACT = "聘用/劳动合同"
    ACHIEVEMENTS = "业绩成果"
    PUBLICATIONS = "论文著作"
    CONTINUING_EDUCATION = "继续教育"


class AuditStatus(str, Enum):
    """材料审核状态"""
    PENDING = "待审核"
    PASSED = "已通过"
    FLAGGED = "已标记问题"


class FeedbackType(str, Enum):
    """机构反馈类型"""
    APPROVED = "通过"
    REJECTED = "不通过"
    REVISE = "返修"


# 状态转换规则：key=当前状态，value=允许的下一个状态列表
VALID_TRANSITIONS = {
    ApplicationStatus.INITIAL: [ApplicationStatus.SUPPLEMENT, ApplicationStatus.COMPLETED],
    ApplicationStatus.SUPPLEMENT: [ApplicationStatus.COMPLETED],
    ApplicationStatus.COMPLETED: [ApplicationStatus.SUBMITTED],
    ApplicationStatus.SUBMITTED: [ApplicationStatus.REVISE, ApplicationStatus.APPROVED, ApplicationStatus.REJECTED],
    ApplicationStatus.REVISE: [ApplicationStatus.SUPPLEMENT, ApplicationStatus.COMPLETED],
    ApplicationStatus.REJECTED: [ApplicationStatus.REAPPLY],
    ApplicationStatus.REAPPLY: [ApplicationStatus.SUPPLEMENT, ApplicationStatus.COMPLETED],
    ApplicationStatus.APPROVED: [],  # 终态
}

# 文件上传配置（materials / reviews / feedback 统一从enums导入）
ALLOWED_FILE_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


class PaymentStatus(str, Enum):
    """收费/回款状态"""
    UNPAID = "未收费"
    PARTIAL = "部分收费"
    PAID = "已结清"
    REFUNDED = "已退款"


class CertificateStatus(str, Enum):
    """证书发放状态"""
    NOT_ISSUED = "未发证"
    ISSUED = "已发证"
    DELIVERED = "已交付"


class CustomerSource(str, Enum):
    """客户来源渠道"""
    REFERRAL = "老客户转介绍"
    ONLINE = "网络渠道"
    OFFLINE = "线下推广"
    PARTNER = "合作机构"
    SELF = "客户自助注册"
    OTHER = "其他"


# ---------- 申报材料清单（按专业类别要求，提交评审机构前校验） ----------
# 通用必传材料：所有申报都必须具备
REQUIRED_MATERIALS_COMMON = [
    MaterialCategory.IDENTITY.value,
    MaterialCategory.EDUCATION.value,
    MaterialCategory.EMPLOYMENT_CONTRACT.value,
]

# 按专业类别追加的必传材料（key 为专业类别关键词，命中即要求）
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
    """返回某专业类别申报所需的必传材料类别列表（去重、保持稳定顺序）"""
    required = list(REQUIRED_MATERIALS_COMMON)
    cat = professional_category or ""
    for keyword, extra in REQUIRED_MATERIALS_BY_CATEGORY.items():
        if keyword in cat:
            for c in extra:
                if c not in required:
                    required.append(c)
    return required


# ---------- 系统参数默认值（可由 SystemConfig 表覆盖，管理员在线调整） ----------
DEFAULT_SYSTEM_CONFIG = {
    "pool_claim_limit": 50,            # 单个业务员可持有的客户上限
    "pool_recovery_days": 7,           # 无跟进自动回收天数
    "sla_hours_after_assign": 24,      # 分配后 SLA 小时数
    "sla_hours_before_review": 48,     # 待审核 SLA 小时数
    "max_file_size_mb": 50,            # 单文件大小上限(MB)
    "login_lockout_threshold": 10,     # 连续登录失败锁定阈值
    "login_lockout_minutes": 15,       # 锁定时长(分钟)
    "reject_duplicate_phone": 0,       # 是否拒绝重复手机号(1/0)
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
