from pydantic import BaseModel, Field, field_serializer, field_validator
from typing import Optional, List
from datetime import datetime, timezone


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    real_name: Optional[str] = None
    email: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(...)
    real_name: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=120)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=2, max_length=50)
    role: Optional[str] = None
    real_name: Optional[str] = Field(None, max_length=50)
    password: Optional[str] = Field(None, min_length=6, max_length=128)
    email: Optional[str] = Field(None, max_length=120)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    id_number: str = Field(..., min_length=15, max_length=18)
    phone: Optional[str] = Field(None, max_length=20)
    education: Optional[str] = Field(None, max_length=50)
    current_title: Optional[str] = Field(None, max_length=100)
    current_title_year: Optional[int] = None
    target_title: Optional[str] = Field(None, max_length=100)
    work_unit: Optional[str] = Field(None, max_length=200)
    position: Optional[str] = Field(None, max_length=100)
    professional_years: Optional[int] = None
    project_experiences: Optional[str] = None
    assigned_salesman_id: Optional[int] = None
    source: Optional[str] = Field(None, max_length=50)

    @field_validator("id_number")
    @classmethod
    def _check_id_number(cls, v: str) -> str:
        """新增客户时校验身份证号校验位（存量数据不校验，避免阻断历史数据编辑）"""
        from utils.validators import validate_id_number, normalize_id_number
        value = normalize_id_number(v)
        err = validate_id_number(value)
        if err:
            raise ValueError(err)
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v):
        from utils.validators import validate_phone
        err = validate_phone(v)
        if err:
            raise ValueError(err)
        return v


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    id_number: Optional[str] = Field(None, min_length=15, max_length=18)
    phone: Optional[str] = Field(None, max_length=20)
    education: Optional[str] = Field(None, max_length=50)
    current_title: Optional[str] = Field(None, max_length=100)
    current_title_year: Optional[int] = None
    target_title: Optional[str] = Field(None, max_length=100)
    work_unit: Optional[str] = Field(None, max_length=200)
    position: Optional[str] = Field(None, max_length=100)
    professional_years: Optional[int] = None
    project_experiences: Optional[str] = None
    # 注意：assigned_salesman_id 已移除 —— 客户归属变更必须走转让接口（有审计和通知）


class CustomerResponse(BaseModel):
    id: int
    name: str
    id_number: str
    phone: Optional[str]
    education: Optional[str]
    current_title: Optional[str]
    current_title_year: Optional[int]
    target_title: Optional[str]
    work_unit: Optional[str]
    position: Optional[str]
    professional_years: Optional[int]
    project_experiences: Optional[str]
    assigned_salesman_id: Optional[int]
    name_pinyin: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationCreate(BaseModel):
    customer_id: int
    professional_category: Optional[str] = Field(None, max_length=100)
    title_level: Optional[str] = Field(None, max_length=100)


class ApplicationUpdate(BaseModel):
    professional_category: Optional[str] = Field(None, max_length=100)
    title_level: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(None, max_length=20)
    # submitted_at / assigned_salesman_id 已移除：submitted_at 由提交动作写入，客户归属属于 Customer
    assigned_reviewer_id: Optional[int] = None
    institution_name: Optional[str] = Field(None, max_length=200)


class ApplicationResponse(BaseModel):
    id: int
    customer_id: int
    professional_category: Optional[str]
    title_level: Optional[str]
    status: str
    batch_number: Optional[str]
    submitted_at: Optional[datetime]
    institution_name: Optional[str]
    assigned_reviewer_id: Optional[int]
    cycle_year: Optional[int] = None
    cycle_deadline: Optional[datetime] = None
    contract_no: Optional[str] = None
    contract_signed_at: Optional[datetime] = None
    fee_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    payment_status: str = "未收费"
    payment_remark: Optional[str] = None
    certificate_status: str = "未发证"
    certificate_no: Optional[str] = None
    certificate_issued_at: Optional[datetime] = None
    certificate_delivered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationFinanceUpdate(BaseModel):
    """收费/合同/证书信息更新（独立于状态流转）"""
    contract_no: Optional[str] = Field(None, max_length=64)
    contract_signed_at: Optional[datetime] = None
    fee_amount: Optional[float] = Field(None, ge=0)
    payment_status: Optional[str] = Field(None, max_length=20)
    payment_remark: Optional[str] = None
    certificate_status: Optional[str] = Field(None, max_length=20)
    certificate_no: Optional[str] = Field(None, max_length=64)
    certificate_issued_at: Optional[datetime] = None
    certificate_delivered_at: Optional[datetime] = None


class PaymentRecordCreate(BaseModel):
    amount: float = Field(..., gt=0)
    paid_at: Optional[datetime] = None
    method: Optional[str] = Field(None, max_length=30)
    remark: Optional[str] = None


class PaymentRecordResponse(BaseModel):
    id: int
    application_id: int
    amount: float
    paid_at: datetime
    method: Optional[str]
    remark: Optional[str]
    created_by_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class MaterialResponse(BaseModel):
    id: int
    application_id: int
    category: str
    filename: str
    file_path: str
    file_size: Optional[int]
    uploader_id: Optional[int]
    audit_status: str
    remark: Optional[str]
    version: int
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewResponse(BaseModel):
    id: int
    material_id: Optional[int]
    application_id: Optional[int]
    reviewer_id: int
    result: str
    issue_type: Optional[str]
    description: Optional[str]
    review_file_path: Optional[str]
    created_at: datetime

    @field_serializer('created_at')
    def serialize_created_at(self, v: datetime) -> str:
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()

    class Config:
        from_attributes = True


class FeedbackResponse(BaseModel):
    id: int
    application_id: int
    feedback_type: str
    content: Optional[str]
    attachment_path: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class RegistrationTokenCreate(BaseModel):
    max_uses: Optional[int] = 0
    expires_days: Optional[int] = 7


class RegistrationTokenResponse(BaseModel):
    id: int
    token: str
    salesman_id: int
    expires_at: datetime
    max_uses: int
    use_count: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SelfRegisterRequest(BaseModel):
    token: str
    name: str
    id_number: str
    phone: Optional[str] = None
    education: Optional[str] = None
    current_title: Optional[str] = None
    current_title_year: Optional[int] = None
    target_title: Optional[str] = None
    work_unit: Optional[str] = None
    position: Optional[str] = None
    professional_years: Optional[int] = None
    project_experiences: Optional[str] = None
    source: Optional[str] = Field(None, max_length=50, description="客户来源渠道")


class OperationLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    username: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[int]
    old_value: Optional[dict]
    new_value: Optional[dict]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class OperationLogListResponse(BaseModel):
    items: List[OperationLogResponse]
    total: int
    page: int
    page_size: int


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    content: str
    type: str
    related_type: Optional[str]
    related_id: Optional[int]
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    total: int
    unread_count: int


class FollowUpResponse(BaseModel):
    id: int
    customer_id: int
    user_id: int
    username: Optional[str] = None
    content: str
    follow_up_type: str
    next_follow_up_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class FollowUpCreate(BaseModel):
    customer_id: int
    content: str
    follow_up_type: str = "phone"
    next_follow_up_at: Optional[datetime] = None
