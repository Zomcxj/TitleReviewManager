from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models import Application, Customer, OperationLog, User
from schemas import ApplicationUpdate, ApplicationResponse
from enums import VALID_TRANSITIONS
from auth import get_current_user
from datetime import datetime, timezone
import uuid
from routers.notifications import create_notification

router = APIRouter(prefix="/api/applications", tags=["申报管理"])


@router.get("/{application_id}")
async def get_application(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    return ApplicationResponse.model_validate(app).model_dump()


@router.put("/{application_id}")
async def update_application(
    application_id: int,
    data: ApplicationUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")

    old_status = app.status
    update_data = data.model_dump(exclude_unset=True)

    if "status" in update_data:
        new_status = update_data["status"]
        if new_status not in VALID_TRANSITIONS.get(old_status, []):
            raise HTTPException(
                status_code=400,
                detail=f"不允许从 '{old_status}' 转换到 '{new_status}'"
            )
        if new_status == "提交评审机构审核":
            app.submitted_at = datetime.now(timezone.utc)
        app.status = new_status
        
        customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
        if customer:
            salesman_id = customer.assigned_salesman_id
            if salesman_id:
                if new_status == "资料补充":
                    create_notification(
                        db=db,
                        user_id=salesman_id,
                        title="需要补充资料",
                        content=f"客户 {customer.name} 的申报需要补充资料",
                        type="status_change",
                        related_type="application",
                        related_id=app.id,
                    )
                elif new_status == "返修":
                    create_notification(
                        db=db,
                        user_id=salesman_id,
                        title="需要返修",
                        content=f"客户 {customer.name} 的申报被退回，需要按意见返修",
                        type="status_change",
                        related_type="application",
                        related_id=app.id,
                    )
                elif new_status == "完成资料":
                    reviewers = db.query(User).filter(User.role == 'reviewer').all()
                    admins = db.query(User).filter(User.role == 'admin').all()
                    for u in reviewers + admins:
                        create_notification(
                            db=db,
                            user_id=u.id,
                            title="新申报待审核",
                            content=f"客户 {customer.name} 已提交审核，请前往审核工作台处理",
                            type="status_change",
                            related_type="application",
                            related_id=app.id,
                        )
                elif new_status in ["通过", "不通过"]:
                    create_notification(
                        db=db,
                        user_id=salesman_id,
                        title=f"审核结果：{new_status}",
                        content=f"客户 {customer.name} 的申报审核结果为：{new_status}",
                        type="status_change",
                        related_type="application",
                        related_id=app.id,
                    )
        
        log = OperationLog(
            user_id=user.get("user_id") or user.get("id"),
            username=user.get("username", ""),
            action=f"状态变更：{old_status} -> {new_status}",
            resource_type="application",
            resource_id=app.id,
            new_value={"detail": f"操作人：{user.get('username')}"},
        )
        db.add(log)

    for key, value in update_data.items():
        if key != "status":
            setattr(app, key, value)

    db.commit()
    db.refresh(app)
    return ApplicationResponse.model_validate(app).model_dump()


@router.post("/{application_id}/submit-to-institution")
async def submit_to_institution(
    application_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    if app.status != "完成资料":
        raise HTTPException(status_code=400, detail="只有完成资料状态才能提交评审机构")
    body = await request.json()
    institution_name = body.get("institution_name", "")
    old_status = app.status
    app.status = "提交评审机构审核"
    app.institution_name = institution_name
    app.submitted_at = datetime.utcnow()
    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action=f"状态变更: {old_status} -> 提交评审机构审核",
        resource_type="application",
        resource_id=app.id,
        new_value={"detail": f"报送机构: {institution_name}"},
    )
    db.add(log)
    db.commit()
    db.refresh(app)
    return ApplicationResponse.model_validate(app).model_dump()


@router.post("/{application_id}/reapply")
async def create_reapplication(
    application_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    old_app = db.query(Application).filter(Application.id == application_id).first()
    if not old_app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    if old_app.status != "不通过":
        raise HTTPException(status_code=400, detail="只有不通过的批次才能发起二次申报")
    new_app = Application(
        customer_id=old_app.customer_id,
        professional_category=old_app.professional_category,
        title_level=old_app.title_level,
        status="二次申报",
        batch_number=f"BATCH-{uuid.uuid4().hex[:8].upper()}-R2",
    )
    db.add(new_app)
    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="发起二次申报",
        resource_type="application",
        resource_id=new_app.id,
        new_value={"detail": f"基于原批次 {old_app.batch_number}"},
    )
    db.add(log)
    db.commit()
    db.refresh(new_app)
    return ApplicationResponse.model_validate(new_app).model_dump()
