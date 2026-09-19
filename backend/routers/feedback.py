from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Feedback, Application, OperationLog
from schemas import FeedbackResponse
from auth import get_current_user, require_role
from enums import (
    ALLOWED_FILE_EXTENSIONS,
    MAX_FILE_SIZE,
    FeedbackType,
    ApplicationStatus,
    VALID_TRANSITIONS,
)
import os
import uuid
from urllib.parse import quote

router = APIRouter(prefix="/api/feedback", tags=["机构反馈"])
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

VALID_FEEDBACK_TYPES = [t.value for t in FeedbackType]


@router.get("/application/{application_id}")
async def get_application_feedbacks(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    # 数据隔离：机构反馈含评审意见，业务员仅能查看自己名下客户的
    from utils.data_scope import assert_can_access_application
    assert_can_access_application(db, user, application_id)
    feedbacks = db.query(Feedback).filter(Feedback.application_id == application_id).all()
    return [FeedbackResponse.model_validate(f).model_dump() for f in feedbacks]


@router.post("/")
async def create_feedback(
    application_id: int = Form(...),
    feedback_type: str = Form(...),
    content: str = Form(None),
    attachment: UploadFile = File(None),
    request: Request = None,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("reviewer", "admin")),
):
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")

    if feedback_type not in VALID_FEEDBACK_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的反馈类型，可选：{VALID_FEEDBACK_TYPES}")

    # 状态机：仅提交评审机构审核状态允许录入机构反馈
    if app.status != ApplicationStatus.SUBMITTED.value:
        raise HTTPException(status_code=400, detail=f"当前状态（{app.status}）不允许录入机构反馈")
    next_states = [s.value for s in VALID_TRANSITIONS.get(ApplicationStatus(app.status), [])]
    if feedback_type not in next_states:
        raise HTTPException(status_code=400, detail=f"当前状态（{app.status}）不允许流转到（{feedback_type}）")

    attachment_path = None
    if attachment and attachment.filename:
        ext = os.path.splitext(attachment.filename)[1].lower()
        if ext not in ALLOWED_FILE_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ext}")
        if attachment.size is not None:
            # 优先使用请求声明的文件大小，超限时不再读取内容
            if attachment.size > MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail=f"文件大小超过限制：{MAX_FILE_SIZE // 1024 // 1024}MB")
            file_content = await attachment.read()
        else:
            file_content = await attachment.read()
            if len(file_content) > MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail=f"文件大小超过限制：{MAX_FILE_SIZE // 1024 // 1024}MB")
        from utils.upload_guard import validate_file_content
        content_err = validate_file_content(attachment.filename, file_content)
        if content_err:
            raise HTTPException(status_code=400, detail=content_err)
        unique_name = f"feedback_{uuid.uuid4().hex}{ext}"
        app_dir = os.path.join(UPLOAD_DIR, str(application_id))
        os.makedirs(app_dir, exist_ok=True)
        attachment_path = f"uploads/{application_id}/{unique_name}"
        full_path = os.path.join(BASE_DIR, attachment_path)
        with open(full_path, "wb") as f:
            f.write(file_content)

    feedback = Feedback(
        application_id=application_id,
        feedback_type=feedback_type,
        content=content,
        attachment_path=attachment_path,
        created_by_id=user["user_id"],
    )
    db.add(feedback)

    old_status = app.status
    if feedback_type == "通过":
        app.status = "通过"
    elif feedback_type == "不通过":
        app.status = "不通过"
    elif feedback_type == "返修":
        app.status = "返修"

    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action=f"录入机构反馈: {feedback_type}",
        resource_type="application",
        resource_id=application_id,
        new_value={"detail": f"原状态: {old_status} -> 新状态: {app.status}。意见: {content or '无'}"},
    )
    db.add(log)
    db.commit()
    db.refresh(feedback)
    return FeedbackResponse.model_validate(feedback).model_dump()


@router.get("/{feedback_id}/attachment")
async def download_feedback_attachment(
    feedback_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """机构反馈附件鉴权下载（/uploads 静态挂载已移除，统一走此端点）"""
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not feedback or not feedback.attachment_path:
        raise HTTPException(status_code=404, detail="附件不存在")
    # 数据隔离：机构反馈附件按客户归属校验
    from utils.data_scope import assert_can_access_application
    assert_can_access_application(db, user, feedback.application_id)
    full_path = os.path.join(BASE_DIR, feedback.attachment_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="附件文件不存在")
    filename = os.path.basename(feedback.attachment_path)
    # RFC 5987: UTF-8 encoded filename for non-ASCII support
    filename_encoded = quote(filename.encode("utf-8"), safe="")
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return FileResponse(
        full_path,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{filename_encoded}"
        },
    )


@router.get("/application/{application_id}/logs")
async def get_operation_logs(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    from utils.data_scope import assert_can_access_application
    assert_can_access_application(db, user, application_id)
    from models import User as UserModel
    logs = db.query(OperationLog).filter(
        OperationLog.resource_type == "application",
        OperationLog.resource_id == application_id
    ).order_by(OperationLog.created_at.desc()).all()
    result = []
    for log in logs:
        user = db.query(UserModel).filter(UserModel.id == log.user_id).first()
        result.append({
            "id": log.id,
            "action": log.action,
            "detail": (log.new_value or {}).get("detail", ""),
            "actor_id": log.user_id,
            "actor_name": log.username or (user.real_name if user else "系统"),
            "created_at": log.created_at,
        })
    return result
