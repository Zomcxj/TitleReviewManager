from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base
from enums import ApplicationStatus, AuditStatus
from utils.timeutil import utcnow


class SystemConfig(Base):
    """System configuration entries (key-value pairs, adjustable online by admins; unconfigured keys fall back to enums.DEFAULT_SYSTEM_CONFIG)"""
    __tablename__ = "system_configs"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    value = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by = Column(String(50), nullable=True)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)
    real_name = Column(String(50))
    email = Column(String(120), nullable=True, comment="邮箱，用于外部通知推送")
    must_change_password = Column(
        Boolean, default=False, nullable=False,
        comment="是否强制修改密码（种子账号/管理员重置后置位，登录后需先改密）",
    )
    password_changed_at = Column(DateTime, nullable=True, comment="最近一次修改密码时间")
    token_version = Column(
        Integer, default=0, nullable=False,
        comment="token 版本；改密/重置/删除时自增，使已签发的旧 token 立即失效",
    )
    created_at = Column(DateTime, default=utcnow)
    is_deleted = Column(Boolean, default=False, nullable=False, index=True, comment="软删除标记")
    deleted_at = Column(DateTime, nullable=True)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, index=True)
    id_number = Column(String(18), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    education = Column(String(50))
    current_title = Column(String(50))
    current_title_year = Column(Integer)
    target_title = Column(String(100), comment="报考职称")
    work_unit = Column(String(200))
    position = Column(String(100))
    professional_years = Column(Integer)
    project_experiences = Column(Text)
    assigned_salesman_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True, comment="归属业务员（业务员数据隔离高频过滤）")
    is_public = Column(Boolean, default=False, index=True, comment="是否在公海池")
    name_pinyin = Column(String(10), index=True, comment="拼音首字母")
    last_follow_up_at = Column(DateTime, nullable=True, comment="最后跟进时间")
    public_at = Column(DateTime, nullable=True, comment="进入公海时间")
    sla_deadline = Column(DateTime, nullable=True, comment="SLA 截止时间")
    source = Column(String(50), nullable=True, comment="客户来源渠道")
    is_deleted = Column(Boolean, default=False, nullable=False, index=True, comment="软删除标记")
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    applications = relationship("Application", back_populates="customer", order_by="Application.id.desc()")
    follow_ups = relationship("FollowUp", back_populates="customer", order_by="FollowUp.id.desc()")
    assigned_salesman = relationship("User", foreign_keys=[assigned_salesman_id])


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    professional_category = Column(String(100))
    title_level = Column(String(50))
    status = Column(String(20), default=ApplicationStatus.INITIAL.value, index=True)
    batch_number = Column(String(50), unique=True)
    submitted_at = Column(DateTime)
    institution_name = Column(String(200))
    assigned_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    review_sla_deadline = Column(
        DateTime, nullable=True, index=True,
        comment="内部审核 SLA 截止时间（进入完成资料时写入，离开待审状态时清空）",
    )
    # Application cycle
    cycle_year = Column(Integer, nullable=True, index=True, comment="申报年度")
    cycle_deadline = Column(DateTime, nullable=True, index=True, comment="该批次申报截止时间")
    # Fees/contract
    contract_no = Column(String(64), nullable=True, index=True, comment="合同编号")
    contract_signed_at = Column(DateTime, nullable=True, comment="合同签订时间")
    fee_amount = Column(Numeric(12, 2), nullable=True, comment="合同金额")
    paid_amount = Column(Numeric(12, 2), nullable=True, default=0, comment="已收金额")
    payment_status = Column(String(20), nullable=False, default="未收费", index=True)
    payment_remark = Column(Text, nullable=True, comment="收费备注/回款记录摘要")
    # Certificate outcome
    certificate_status = Column(String(20), nullable=False, default="未发证", index=True)
    certificate_no = Column(String(64), nullable=True, comment="证书编号")
    certificate_issued_at = Column(DateTime, nullable=True, comment="发证日期")
    certificate_delivered_at = Column(DateTime, nullable=True, comment="证书交付客户时间")
    is_deleted = Column(Boolean, default=False, nullable=False, index=True, comment="软删除标记")
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    customer = relationship("Customer", back_populates="applications")
    materials = relationship("Material", back_populates="application")
    reviews = relationship("Review", back_populates="application")
    feedbacks = relationship("Feedback", back_populates="application")
    payment_records = relationship("PaymentRecord", back_populates="application", order_by="PaymentRecord.id.desc()")
    assigned_reviewer = relationship("User", foreign_keys=[assigned_reviewer_id])


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        # Version must be unique for the same application+category — a DB-level backstop preventing duplicate versions from concurrent uploads
        UniqueConstraint("application_id", "category", "version", name="uq_material_app_category_version"),
    )
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    category = Column(String(30), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    audit_status = Column(String(20), default=AuditStatus.PENDING.value, index=True)
    remark = Column(Text)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    application = relationship("Application", back_populates="materials")
    uploader = relationship("User", foreign_keys=[uploader_id])
    reviews = relationship("Review", back_populates="material")


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True, index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    result = Column(String(20), nullable=False)
    issue_type = Column(String(50))
    description = Column(Text)
    review_file_path = Column(String(500))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    material = relationship("Material", back_populates="reviews")
    application = relationship("Application", back_populates="reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id])


class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    feedback_type = Column(String(20), nullable=False)
    content = Column(Text)
    attachment_path = Column(String(500))
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    application = relationship("Application", back_populates="feedbacks")
    created_by = relationship("User", foreign_keys=[created_by_id])


class OperationLog(Base):
    __tablename__ = "operation_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String(50), index=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(Integer, nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    # Tamper-proof hash chain: prev_hash is the previous entry's entry_hash, and entry_hash is
    # the SHA-256 of this entry's content + prev_hash. Any modified/deleted entry breaks the
    # chain for all later ones, detectable via verify_chain(). See utils/audit_chain.py
    prev_hash = Column(String(64), nullable=True, comment="前一条日志的哈希")
    entry_hash = Column(String(64), nullable=True, index=True, comment="本条日志的链式哈希")

    user = relationship("User", foreign_keys=[user_id])


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(128), unique=True, nullable=False, index=True)
    salesman_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    max_uses = Column(Integer, default=0)
    use_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    salesman = relationship("User", foreign_keys=[salesman_id])


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(50), nullable=False, index=True)
    related_type = Column(String(50), nullable=True)
    related_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = relationship("User", foreign_keys=[user_id])


class FollowUp(Base):
    __tablename__ = "follow_ups"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    follow_up_type = Column(String(50), default="phone", nullable=False)
    next_follow_up_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    customer = relationship("Customer", back_populates="follow_ups")
    user = relationship("User", foreign_keys=[user_id])


class PaymentRecord(Base):
    """Payment record details (one contract can be paid in multiple installments)"""
    __tablename__ = "payment_records"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    paid_at = Column(DateTime, nullable=False, default=utcnow)
    method = Column(String(30), nullable=True, comment="收款方式：现金/转账/微信/支付宝")
    remark = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    application = relationship("Application", back_populates="payment_records")
    created_by = relationship("User", foreign_keys=[created_by_id])


class LoginAttempt(Base):
    """Login attempt records (database-backed and shared across workers, so rate limiting is not multiplied by worker count)"""
    __tablename__ = "login_attempts"
    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(20), nullable=False, index=True, comment="ip 或 account")
    key = Column(String(120), nullable=False, index=True, comment="IP 地址或用户名")
    attempted_at = Column(DateTime, default=utcnow, index=True)
    success = Column(Boolean, default=False, nullable=False, comment="该次尝试是否成功")


class AccountLock(Base):
    """Account lockout state (database-backed, shared across workers)"""
    __tablename__ = "account_locks"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    failed_count = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class UserSession(Base):
    """Login sessions (one per device/browser, for session management and single-device sign-out).

    JWT is stateless by itself and cannot revoke an individual token. This records one
    session per login; the token carries a session_id which is verified as still valid
    during authentication — enabling:
    - viewing your own active devices
    - kicking a single device (e.g. a lost phone)
    - keeping only the current session on password change and invalidating all others
    """
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True, comment="会话标识（写入 token）")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(255), nullable=True, comment="原始 UA，用于识别设备")
    device_label = Column(String(100), nullable=True, comment="解析后的设备描述，如 Chrome / Windows")
    created_at = Column(DateTime, default=utcnow, index=True)
    last_seen_at = Column(DateTime, default=utcnow, comment="最近活跃时间")
    expires_at = Column(DateTime, nullable=False, comment="过期时间（与 token 有效期一致）")
    revoked_at = Column(DateTime, nullable=True, comment="被主动下线的时间；非空即失效")

    user = relationship("User", foreign_keys=[user_id])


class ClientError(Base):
    """Frontend error reports (for troubleshooting production issues).

    Frontend errors used to only pop up in the user's browser, so diagnosis relied entirely
    on the user's description ("it errors when I click that button"). This collects them on
    the backend so admins can see real stack traces and occurrence frequency.
    """
    __tablename__ = "client_errors"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String(50), nullable=True, index=True)
    message = Column(Text, nullable=False, comment="错误信息")
    stack = Column(Text, nullable=True, comment="堆栈（截断保存）")
    url = Column(String(500), nullable=True, comment="出错页面路径")
    user_agent = Column(String(255), nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])
