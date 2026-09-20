from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    real_name: str | None = None
    email: str | None = None
    must_change_password: bool = False
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(...)
    real_name: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=120)


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=2, max_length=50)
    role: str | None = None
    real_name: str | None = Field(None, max_length=50)
    password: str | None = Field(None, min_length=6, max_length=128)
    email: str | None = Field(None, max_length=120)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_strength(cls, v: str) -> str:
        """自助改密时校验强度：拒绝常见弱口令、纯数字、纯字母"""
        from utils.validators import check_password_strength
        err = check_password_strength(v)
        if err:
            raise ValueError(err)
        return v


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    id_number: str = Field(..., min_length=15, max_length=18)
    phone: str | None = Field(None, max_length=20)
    education: str | None = Field(None, max_length=50)
    current_title: str | None = Field(None, max_length=100)
    current_title_year: int | None = None
    target_title: str | None = Field(None, max_length=100)
    work_unit: str | None = Field(None, max_length=200)
    position: str | None = Field(None, max_length=100)
    professional_years: int | None = None
    project_experiences: str | None = None
    assigned_salesman_id: int | None = None
    source: str | None = Field(None, max_length=50)

    @field_validator("id_number")
    @classmethod
    def _check_id_number(cls, v: str) -> str:
        """新增客户时校验身份证号校验位（存量数据不校验，避免阻断历史数据编辑）"""
        from utils.validators import normalize_id_number, validate_id_number
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
    name: str | None = Field(None, max_length=50)
    id_number: str | None = Field(None, min_length=15, max_length=18)
    phone: str | None = Field(None, max_length=20)
    education: str | None = Field(None, max_length=50)
    current_title: str | None = Field(None, max_length=100)
    current_title_year: int | None = None
    target_title: str | None = Field(None, max_length=100)
    work_unit: str | None = Field(None, max_length=200)
    position: str | None = Field(None, max_length=100)
    professional_years: int | None = None
    project_experiences: str | None = None
    # 注意：assigned_salesman_id 已移除 —— 客户归属变更必须走转让接口（有审计和通知）


class CustomerResponse(BaseModel):
    id: int
    name: str
    id_number: str
    phone: str | None
    education: str | None
    current_title: str | None
    current_title_year: int | None
    target_title: str | None
    work_unit: str | None
    position: str | None
    professional_years: int | None
    project_experiences: str | None
    assigned_salesman_id: int | None
    name_pinyin: str | None = None
    source: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApplicationCreate(BaseModel):
    customer_id: int
    professional_category: str | None = Field(None, max_length=100)
    title_level: str | None = Field(None, max_length=100)


class ApplicationUpdate(BaseModel):
    professional_category: str | None = Field(None, max_length=100)
    title_level: str | None = Field(None, max_length=100)
    status: str | None = Field(None, max_length=20)
    # submitted_at / assigned_salesman_id 已移除：submitted_at 由提交动作写入，客户归属属于 Customer
    assigned_reviewer_id: int | None = None
    institution_name: str | None = Field(None, max_length=200)


class ApplicationResponse(BaseModel):
    id: int
    customer_id: int
    professional_category: str | None
    title_level: str | None
    status: str
    batch_number: str | None
    submitted_at: datetime | None
    institution_name: str | None
    assigned_reviewer_id: int | None
    review_sla_deadline: datetime | None = None
    cycle_year: int | None = None
    cycle_deadline: datetime | None = None
    contract_no: str | None = None
    contract_signed_at: datetime | None = None
    fee_amount: float | None = None
    paid_amount: float | None = None
    payment_status: str = "未收费"
    payment_remark: str | None = None
    certificate_status: str = "未发证"
    certificate_no: str | None = None
    certificate_issued_at: datetime | None = None
    certificate_delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApplicationFinanceUpdate(BaseModel):
    """收费/合同/证书信息更新（独立于状态流转）"""
    contract_no: str | None = Field(None, max_length=64)
    contract_signed_at: datetime | None = None
    fee_amount: float | None = Field(None, ge=0)
    payment_status: str | None = Field(None, max_length=20)
    payment_remark: str | None = None
    certificate_status: str | None = Field(None, max_length=20)
    certificate_no: str | None = Field(None, max_length=64)
    certificate_issued_at: datetime | None = None
    certificate_delivered_at: datetime | None = None


class PaymentRecordCreate(BaseModel):
    amount: float = Field(..., gt=0)
    paid_at: datetime | None = None
    method: str | None = Field(None, max_length=30)
    remark: str | None = None


class PaymentRecordResponse(BaseModel):
    id: int
    application_id: int
    amount: float
    paid_at: datetime
    method: str | None
    remark: str | None
    created_by_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaterialResponse(BaseModel):
    id: int
    application_id: int
    category: str
    filename: str
    file_path: str
    file_size: int | None
    uploader_id: int | None
    audit_status: str
    remark: str | None
    version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewResponse(BaseModel):
    id: int
    material_id: int | None
    application_id: int | None
    reviewer_id: int
    result: str
    issue_type: str | None
    description: str | None
    review_file_path: str | None
    created_at: datetime

    @field_serializer('created_at')
    def serialize_created_at(self, v: datetime) -> str:
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()

    model_config = ConfigDict(from_attributes=True)


class FeedbackResponse(BaseModel):
    id: int
    application_id: int
    feedback_type: str
    content: str | None
    attachment_path: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RegistrationTokenCreate(BaseModel):
    max_uses: int | None = 0
    expires_days: int | None = 7


class RegistrationTokenResponse(BaseModel):
    id: int
    token: str
    salesman_id: int
    expires_at: datetime
    max_uses: int
    use_count: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SelfRegisterRequest(BaseModel):
    token: str
    name: str
    id_number: str
    phone: str | None = None
    education: str | None = None
    current_title: str | None = None
    current_title_year: int | None = None
    target_title: str | None = None
    work_unit: str | None = None
    position: str | None = None
    professional_years: int | None = None
    project_experiences: str | None = None
    source: str | None = Field(None, max_length=50, description="客户来源渠道")


class OperationLogResponse(BaseModel):
    id: int
    user_id: int | None
    username: str | None
    action: str
    resource_type: str
    resource_id: int | None
    old_value: dict | None
    new_value: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OperationLogListResponse(BaseModel):
    items: list[OperationLogResponse]
    total: int
    page: int
    page_size: int


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    content: str
    type: str
    related_type: str | None
    related_id: int | None
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int


class FollowUpResponse(BaseModel):
    id: int
    customer_id: int
    user_id: int
    username: str | None = None
    content: str
    follow_up_type: str
    next_follow_up_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FollowUpCreate(BaseModel):
    customer_id: int
    content: str
    follow_up_type: str = "phone"
    next_follow_up_at: datetime | None = None
