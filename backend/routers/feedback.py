from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.orm import Session
from database import get_db
from models import Feedback, Application, OperationLog
from schemas import FeedbackResponse
from auth import get_current_user
from datetime import datetime
import os
import uuid

router = APIRouter(prefix="/api/feedback", tags=["机构反馈"])
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


@router.get("/application/{application_id}")
async def get_application_feedbacks(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
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
):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")

    attachment_path = None
    if attachment:
        ext = os.path.splitext(attachment.filename)[1]
        unique_name = f"feedback_{uuid.uuid4().hex}{ext}"
        app_dir = os.path.join(UPLOAD_DIR, str(application_id))
        os.makedirs(app_dir, exist_ok=True)
        attachment_path = f"uploads/{application_id}/{unique_name}"
        full_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), attachment_path)
        file_content = await attachment.read()
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


@router.get("/application/{application_id}/logs")
async def get_operation_logs(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
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
