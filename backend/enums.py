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

# 文件上传配置
ALLOWED_FILE_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# 认证配置
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 480
MAX_LOGIN_ATTEMPTS = 5
RATE_WINDOW_SECONDS = 300  # 5 minutes
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes
