from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.orm import Session
from database import get_db
from models import Review, Material, Application, User, OperationLog
from schemas import ReviewCreate, ReviewResponse
from auth import get_current_user
from datetime import datetime
import os
import uuid
from routers.notifications import create_notification

router = APIRouter(prefix="/api/reviews", tags=["审核"])
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


@router.get("/application/{application_id}")
async def get_application_reviews(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    reviews = db.query(Review).filter(Review.application_id == application_id).all()
    return [ReviewResponse.model_validate(r).model_dump() for r in reviews]


@router.get("/material/{material_id}")
async def get_material_reviews(material_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    reviews = db.query(Review).filter(Review.material_id == material_id).all()
    return [ReviewResponse.model_validate(r).model_dump() for r in reviews]


@router.post("/")
async def create_review(
    request: Request,
    material_id: int = Form(None),
    application_id: int = Form(None),
    result: str = Form(...),
    issue_type: str = Form(None),
    description: str = Form(None),
    review_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    review_file_path = None
    if review_file:
        ext = os.path.splitext(review_file.filename)[1]
        unique_name = f"review_{uuid.uuid4().hex}{ext}"
        app_dir = os.path.join(UPLOAD_DIR, str(application_id or "reviews"))
        os.makedirs(app_dir, exist_ok=True)
        review_file_path = f"uploads/{application_id or 'reviews'}/{unique_name}"
        full_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), review_file_path)
        content = await review_file.read()
        with open(full_path, "wb") as f:
            f.write(content)

    review = Review(
        material_id=material_id,
        application_id=application_id,
        reviewer_id=user["user_id"],
        result=result,
        issue_type=issue_type,
        description=description,
        review_file_path=review_file_path,
    )
    db.add(review)

    if material_id:
        material = db.query(Material).filter(Material.id == material_id).first()
        if material:
            material.audit_status = "已通过" if result == "通过" else "已标记问题"

    if application_id:
        app = db.query(Application).filter(Application.id == application_id).first()
        if app:
            action_name = "审核通过" if result == "通过" else "退回业务员"
            log = OperationLog(
                user_id=user.get("user_id") or user.get("id"),
                username=user.get("username", ""),
                action=action_name,
                resource_type="application",
                resource_id=application_id,
                new_value={"detail": f"审核员 {user.get('username')} {action_name}。说明: {description or '无'}"},
            )
            db.add(log)

    db.commit()
    db.refresh(review)

    # 取材料名称供通知使用
    material_name = material.name if material_id and material else ""

    # 单条退回/通过时发送通知给业务员和管理员
    if application_id and result in ("退回", "通过") and material_id:
        app = db.query(Application).filter(Application.id == application_id).first()
        if app:
            customer = app.customer
            if customer and customer.assigned_salesman_id:
                if result == "退回":
                    title = "材料退回通知"
                    content = f"客户 {customer.name} 的材料「{material_name}」已被退回"
                else:
                    title = "材料审核通过"
                    content = f"客户 {customer.name} 的材料「{material_name}」已通过审核"
                create_notification(
                    db=db,
                    user_id=customer.assigned_salesman_id,
                    title=title,
                    content=content,
                    type="status_change",
                    related_type="material",
                    related_id=material_id,
                )
            admins = db.query(User).filter(User.role == "admin").all()
            for admin in admins:
                if result == "退回":
                    title = "材料退回通知"
                    content = f"客户 {customer.name if customer else ''} 的材料已被退回" if customer else "材料已被退回"
                else:
                    title = "材料审核通过"
                    content = f"客户 {customer.name if customer else ''} 的材料已通过审核" if customer else "材料已通过审核"
                create_notification(
                    db=db,
                    user_id=admin.id,
                    title=title,
                    content=content,
                    type="status_change",
                    related_type="material",
                    related_id=material_id,
                )

    return ReviewResponse.model_validate(review).model_dump()


@router.post("/batch-review")
async def batch_review(
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    body = await request.json()
    application_id = body.get("application_id")
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    overall_result = body.get("overall_result")
    review_details = body.get("review_details", [])
    description = body.get("description", "")

    if overall_result == "通过":
        materials = db.query(Material).filter(Material.application_id == application_id).all()
        for m in materials:
            m.audit_status = "已通过"
            r = Review(
                material_id=m.id,
                application_id=application_id,
                reviewer_id=user["user_id"],
                result="通过",
                description=description,
            )
            db.add(r)
        app.status = "完成资料"
        log = OperationLog(
            user_id=user.get("user_id") or user.get("id"),
            username=user.get("username", ""),
            action="审核通过全部材料",
            resource_type="application",
            resource_id=application_id,
            new_value={"detail": f"状态变更为完成资料。审核员: {user.get('username')}"},
        )
        db.add(log)
    else:
        for detail in review_details:
            m = db.query(Material).filter(Material.id == detail["material_id"]).first()
            if m:
                m.audit_status = "已标记问题"
                r = Review(
                    material_id=m.id,
                    application_id=application_id,
                    reviewer_id=user["user_id"],
                    result="退回",
                    issue_type=detail.get("issue_type", "内容问题"),
                    description=detail.get("description", ""),
                )
                db.add(r)
        app.status = "资料补充"
        log = OperationLog(
            user_id=user.get("user_id") or user.get("id"),
            username=user.get("username", ""),
            action="退回补充材料",
            resource_type="application",
            resource_id=application_id,
            new_value={"detail": f"退回 {len(review_details)} 项材料。审核员: {user.get('username')}"},
        )
        db.add(log)

    # 发送通知
    customer = app.customer
    if customer and customer.assigned_salesman_id:
        if overall_result == "通过":
            title = "审核通过通知"
            content = f"客户 {customer.name} 的申报材料已全部审核通过"
        else:
            title = "材料退回通知"
            content = f"客户 {customer.name} 的申报材料已被退回，需要补充"
        create_notification(
            db=db,
            user_id=customer.assigned_salesman_id,
            title=title,
            content=content,
            type="status_change",
            related_type="application",
            related_id=application_id,
        )
    admins = db.query(User).filter(User.role == "admin").all()
    for admin in admins:
        if overall_result == "通过":
            title = "审核通过通知"
            content = f"客户 {customer.name} 的申报材料已全部审核通过" if customer else "申报材料已全部审核通过"
        else:
            title = "材料退回通知"
            content = f"客户 {customer.name} 的申报材料已被退回，需要补充" if customer else "申报材料已被退回，需要补充"
        create_notification(
            db=db,
            user_id=admin.id,
            title=title,
            content=content,
            type="status_change",
            related_type="application",
            related_id=application_id,
        )

    db.commit()
    return {"message": "批量审核完成", "new_status": app.status}
