from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enums import (
    UserRole,
    ApplicationStatus,
    MaterialCategory,
    AuditStatus,
    FeedbackType,
    VALID_TRANSITIONS,
)


class ProjectExperience(BaseModel):
    name: str
    start_date: str
    end_date: str
    role: str
    description: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    real_name: Optional[str] = None

    class Config:
        from_attributes = True


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    id_number: str = Field(..., min_length=15, max_length=18)
    phone: Optional[str] = Field(None, max_length=20)
    education: Optional[str] = Field(None, max_length=50)
    current_title: Optional[str] = Field(None, max_length=100)
    current_title_year: Optional[int] = None
    work_unit: Optional[str] = Field(None, max_length=200)
    position: Optional[str] = Field(None, max_length=100)
    professional_years: Optional[int] = None
    project_experiences: Optional[str] = None
    assigned_salesman_id: Optional[int] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    id_number: Optional[str] = Field(None, min_length=15, max_length=18)
    phone: Optional[str] = Field(None, max_length=20)
    education: Optional[str] = Field(None, max_length=50)
    current_title: Optional[str] = Field(None, max_length=100)
    current_title_year: Optional[int] = None
    work_unit: Optional[str] = Field(None, max_length=200)
    position: Optional[str] = Field(None, max_length=100)
    professional_years: Optional[int] = None
    project_experiences: Optional[str] = None
    assigned_salesman_id: Optional[int] = None


class CustomerResponse(BaseModel):
    id: int
    name: str
    id_number: str
    phone: Optional[str]
    education: Optional[str]
    current_title: Optional[str]
    current_title_year: Optional[int]
    work_unit: Optional[str]
    position: Optional[str]
    professional_years: Optional[int]
    project_experiences: Optional[str]
    assigned_salesman_id: Optional[int]
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
    assigned_salesman_id: Optional[int] = None
    assigned_reviewer_id: Optional[int] = None
    institution_name: Optional[str] = Field(None, max_length=200)
    submitted_at: Optional[datetime] = None


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
    created_at: datetime
    updated_at: datetime

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


class ReviewCreate(BaseModel):
    material_id: Optional[int] = None
    application_id: Optional[int] = None
    result: str
    issue_type: Optional[str] = None
    description: Optional[str] = None


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

    class Config:
        from_attributes = True


class FeedbackCreate(BaseModel):
    application_id: int
    feedback_type: str
    content: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: int
    application_id: int
    feedback_type: str
    content: Optional[str]
    attachment_path: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class OperationLogResponse(BaseModel):
    id: int
    application_id: Optional[int]
    customer_id: Optional[int]
    action: str
    detail: Optional[str]
    actor_id: Optional[int]
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
    work_unit: Optional[str] = None
    position: Optional[str] = None
    professional_years: Optional[int] = None
    project_experiences: Optional[str] = None


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


class NotificationCreate(BaseModel):
    user_id: int
    title: str
    content: str
    type: str
    related_type: Optional[str] = None
    related_id: Optional[int] = None


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
