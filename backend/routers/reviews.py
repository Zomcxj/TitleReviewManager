import os
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_role
from database import get_db
from enums import ALLOWED_FILE_EXTENSIONS, MAX_FILE_SIZE
from models import Application, Material, OperationLog, Review, User
from routers.notifications import create_notification
from schemas import ReviewResponse

router = APIRouter(prefix="/api/reviews", tags=["审核"])
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")


@router.get("/pending")
async def list_pending_reviews(
    status: str | None = Query(None, description="完成资料 / 资料补充 / 二次申报"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Internal pending-review queue (ordered by pending materials and review SLA)."""
    from utils.workbench import list_pending_reviews as _list
    return _list(db, current_user, status=status, limit=200)


@router.get("/application/{application_id}")
async def get_application_reviews(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    # Data isolation: salesmen can only view review records of their own customers
    from utils.data_scope import assert_can_access_application
    assert_can_access_application(db, user, application_id)
    reviews = db.query(Review).filter(Review.application_id == application_id).all()
    return [ReviewResponse.model_validate(r).model_dump() for r in reviews]


@router.get("/material/{material_id}")
async def get_material_reviews(material_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    # Data isolation: salesmen can only view review records of their own customers' materials
    from utils.data_scope import assert_can_access_material
    assert_can_access_material(db, user, material_id)
    reviews = db.query(Review).filter(Review.material_id == material_id).all()
    return [ReviewResponse.model_validate(r).model_dump() for r in reviews]


@router.post("/")
async def create_review(
    material_id: int = Form(None),
    application_id: int = Form(None),
    result: str = Form(...),
    issue_type: str = Form(None),
    description: str = Form(None),
    review_file: UploadFile = File(None),
    user: dict = Depends(require_role("reviewer", "admin")),
    db: Session = Depends(get_db),
):
    if result not in ("通过", "退回"):
        raise HTTPException(status_code=400, detail="无效的审核结果")

    material = None
    if material_id:
        material = db.query(Material).filter(Material.id == material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="材料不存在")

    review_file_path = None
    if review_file and review_file.filename:
        ext = os.path.splitext(review_file.filename)[1].lower()
        if ext not in ALLOWED_FILE_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ext}")
        # Size check BEFORE reading any content: an oversized upload is rejected
        # without buffering it
        if review_file.size is not None and review_file.size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制：{MAX_FILE_SIZE // 1024 // 1024}MB")
        from utils.upload_guard import validate_file_content
        head = await review_file.read(64)
        if not head and (review_file.size or 0) > 0:
            raise HTTPException(status_code=400, detail="文件内容为空")
        content_err = validate_file_content(review_file.filename, head)
        if content_err:
            raise HTTPException(status_code=400, detail=content_err)
        await review_file.seek(0)  # rewind so the chunked write starts from the beginning
        unique_name = f"review_{uuid.uuid4().hex}{ext}"
        app_dir = os.path.join(UPLOAD_DIR, str(application_id or "reviews"))
        os.makedirs(app_dir, exist_ok=True)
        review_file_path = f"uploads/{application_id or 'reviews'}/{unique_name}"
        full_path = os.path.join(BASE_DIR, review_file_path)
        # Chunked write: peak memory is one 1MB chunk instead of the whole file
        written = 0
        try:
            with open(full_path, "wb") as f:
                while True:
                    chunk = await review_file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_FILE_SIZE:
                        raise ValueError("size cap exceeded")
                    f.write(chunk)
        except ValueError:
            os.remove(full_path)  # a truncated file is worse than no file
            raise HTTPException(status_code=400, detail=f"文件大小超过限制：{MAX_FILE_SIZE // 1024 // 1024}MB") from None

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

    # Fetch the material name for notifications
    material_name = material.category if material else ""

    # Send notifications to the salesman and admins on single return/pass
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
        # create_notification only adds to the session without committing; commit notifications here
        db.commit()

    return ReviewResponse.model_validate(review).model_dump()


@router.post("/batch-review")
async def batch_review(
    request: Request,
    user: dict = Depends(require_role("reviewer", "admin")),
    db: Session = Depends(get_db),
):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception as e:
        raise HTTPException(status_code=400, detail="请求体格式错误") from e
    application_id = body.get("application_id")
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    overall_result = body.get("overall_result")
    review_details = body.get("review_details", [])
    if not isinstance(review_details, list):
        review_details = []
    description = body.get("description", "")

    if overall_result not in ("通过", "退回"):
        raise HTTPException(status_code=400, detail="无效的审核结果")

    # State machine alignment: validate the current status separately for pass and return
    if overall_result == "通过":
        if app.status not in ("完成资料", "资料补充"):
            raise HTTPException(
                status_code=400,
                detail=f"当前状态（{app.status}）不允许批量审核通过，仅完成资料/资料补充状态可审核",
            )
    else:
        if app.status != "完成资料":
            raise HTTPException(
                status_code=400,
                detail=f"当前状态（{app.status}）不允许批量退回，仅完成资料状态可退回",
            )
        if not review_details:
            raise HTTPException(status_code=400, detail="请至少标记一项问题材料")

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
        from utils.workbench import clear_review_sla
        clear_review_sla(app)
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
        processed_count = 0
        for detail in review_details:
            if not isinstance(detail, dict):
                continue
            detail_material_id = detail.get("material_id")
            if not detail_material_id:
                continue
            # Only allow flagging materials that belong to this application
            m = db.query(Material).filter(
                Material.id == detail_material_id,
                Material.application_id == application_id,
            ).first()
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
                processed_count += 1
        app.status = "资料补充"
        log = OperationLog(
            user_id=user.get("user_id") or user.get("id"),
            username=user.get("username", ""),
            action="退回补充材料",
            resource_type="application",
            resource_id=application_id,
            new_value={"detail": f"退回 {processed_count} 项材料。审核员: {user.get('username')}"},
        )
        db.add(log)

    # Send notifications
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


@router.get("/{review_id}/attachment")
async def download_review_attachment(
    review_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Authenticated download of review attachments (the /uploads static mount has been removed; this endpoint is the unified path)"""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review or not review.review_file_path:
        raise HTTPException(status_code=404, detail="附件不存在")
    # Data isolation: review attachments may contain customer material images
    if review.application_id:
        from utils.data_scope import assert_can_access_application
        assert_can_access_application(db, user, review.application_id)
    full_path = os.path.join(BASE_DIR, review.review_file_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="附件文件不存在")
    filename = os.path.basename(review.review_file_path)
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
