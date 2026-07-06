from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Enum, Float, Boolean, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from database import Base
from enums import ApplicationStatus, AuditStatus


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    password = Column(String(128), nullable=True, comment="明文密码，仅管理员管理用")
    role = Column(String(20), nullable=False)
    real_name = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


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
    assigned_salesman_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_public = Column(Boolean, default=False, index=True, comment="是否在公海池")
    name_pinyin = Column(String(10), index=True, comment="拼音首字母")
    last_follow_up_at = Column(DateTime, nullable=True, comment="最后跟进时间")
    public_at = Column(DateTime, nullable=True, comment="进入公海时间")
    sla_deadline = Column(DateTime, nullable=True, comment="SLA 截止时间")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    applications = relationship("Application", back_populates="customer", order_by="Application.id.desc()")
    follow_ups = relationship("FollowUp", back_populates="customer", order_by="FollowUp.id.desc()")
    assigned_salesman = relationship("User", foreign_keys=[assigned_salesman_id])


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    professional_category = Column(String(100))
    title_level = Column(String(50))
    status = Column(String(20), default=ApplicationStatus.INITIAL.value)
    batch_number = Column(String(50), unique=True)
    submitted_at = Column(DateTime)
    institution_name = Column(String(200))
    assigned_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="applications")
    materials = relationship("Material", back_populates="application")
    reviews = relationship("Review", back_populates="application")
    feedbacks = relationship("Feedback", back_populates="application")
    assigned_reviewer = relationship("User", foreign_keys=[assigned_reviewer_id])


class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    category = Column(String(30), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    audit_status = Column(String(20), default=AuditStatus.PENDING.value)
    remark = Column(Text)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    application = relationship("Application", back_populates="materials")
    uploader = relationship("User", foreign_keys=[uploader_id])
    reviews = relationship("Review", back_populates="material")


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
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
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    feedback_type = Column(String(20), nullable=False)
    content = Column(Text)
    attachment_path = Column(String(500))
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
