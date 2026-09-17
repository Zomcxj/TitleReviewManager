from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from database import get_db
from models import Customer, Application, User, OperationLog
from auth import get_current_user, require_role
from datetime import datetime, timedelta
from routers.notifications import create_notification
from routers.applications import build_material_checklist
from typing import List

router = APIRouter(prefix="/api/batch", tags=["批量操作"])


@router.post("/assign-customers")
async def batch_assign_customers(
    customer_ids: List[int] = Body(..., embed=True),
    salesman_id: int = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="只有管理员可以批量分配客户")
    
    salesman = db.query(User).filter(User.id == salesman_id, User.role == "salesman").first()
    if not salesman:
        raise HTTPException(status_code=404, detail="指定业务员不存在")
    
    updated_count = 0
    for customer_id in customer_ids:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            old_salesman_id = customer.assigned_salesman_id
            customer.assigned_salesman_id = salesman_id
            customer.is_public = False
            customer.sla_deadline = datetime.utcnow() + timedelta(hours=24)
            updated_count += 1
            
            if old_salesman_id and old_salesman_id != salesman_id:
                create_notification(
                    db=db,
                    user_id=old_salesman_id,
                    title="客户调出",
                    content=f"客户 {customer.name} 已被调出给 {salesman.real_name or salesman.username}",
                    type="batch_assign",
                    related_type="customer",
                    related_id=customer.id,
                )
            
            create_notification(
                db=db,
                user_id=salesman_id,
                title="客户分配",
                content=f"你被分配了新客户 {customer.name}",
                type="batch_assign",
                related_type="customer",
                related_id=customer.id,
            )
    
    db.commit()
    return {"message": f"成功分配 {updated_count} 个客户"}


@router.post("/review-batch")
async def batch_review(
    application_ids: List[int] = Body(..., embed=True),
    status: str = Body(..., embed=True),
    description: str = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from models import Review
    from enums import VALID_TRANSITIONS
    
    if current_user.get("role") not in ["reviewer", "admin"]:
        raise HTTPException(status_code=403, detail="只有审核员可以批量审核")
    
    if status not in ["通过", "不通过", "返修"]:
        raise HTTPException(status_code=400, detail="状态无效")
    
    updated_count = 0
    for app_id in application_ids:
        app = db.query(Application).filter(Application.id == app_id).first()
        if not app:
            continue
        
        if status not in VALID_TRANSITIONS.get(app.status, []):
            continue
        
        app.status = status
        
        review = Review(
            application_id=app.id,
            reviewer_id=current_user.get("user_id") or current_user.get("id"),
            result=status,
            description=description or "",
        )
        db.add(review)
        updated_count += 1
        
        customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
        if customer and customer.assigned_salesman_id:
            create_notification(
                db=db,
                user_id=customer.assigned_salesman_id,
                title=f"批量审核结果：{status}",
                content=f"客户 {customer.name} 的申报已被{status}",
                type="batch_review",
                related_type="application",
                related_id=app.id,
            )
    
    db.commit()
    return {"message": f"成功审核 {updated_count} 个批次"}


@router.post("/release-customers")
async def batch_release_customers(
    customer_ids: List[int] = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="只有管理员可以批量释放")
    
    updated_count = 0
    for customer_id in customer_ids:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            old_salesman_id = customer.assigned_salesman_id
            customer.assigned_salesman_id = None
            customer.is_public = True
            customer.public_at = datetime.utcnow()
            updated_count += 1
            
            if old_salesman_id:
                create_notification(
                    db=db,
                    user_id=old_salesman_id,
                    title="客户被释放",
                    content=f"你的客户 {customer.name} 已被释放到公海池",
                    type="batch_release",
                    related_type="customer",
                    related_id=customer.id,
                )
    
    db.commit()
    return {"message": f"成功释放 {updated_count} 个客户到公海池"}


def _skip(application_id: int, batch_number, reason: str) -> dict:
    return {
        "application_id": application_id,
        "batch_number": batch_number,
        "reason": reason,
    }


@router.post("/submit-to-institution")
async def batch_submit_to_institution(
    application_ids: List[int] = Body(..., embed=True),
    institution_name: str = Body("", embed=True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "salesman")),
):
    """批量提交评审机构：逐条校验状态/归属/材料完备性，通过者统一流转并通知。"""
    from enums import ApplicationStatus

    target_status = ApplicationStatus.SUBMITTED.value
    ready_status = ApplicationStatus.COMPLETED.value
    role = current_user.get("role")
    user_id = current_user.get("user_id") or current_user.get("id")
    username = current_user.get("username", "")
    institution_name = (institution_name or "").strip()

    success = 0
    skipped = []

    for application_id in application_ids:
        app = (
            db.query(Application)
            .filter(Application.id == application_id, Application.is_deleted == False)  # noqa: E712
            .first()
        )
        if not app:
            skipped.append(_skip(application_id, None, "批次不存在"))
            continue
        if app.status != ready_status:
            skipped.append(_skip(application_id, app.batch_number, f"当前状态 {app.status} 不允许提交"))
            continue

        customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
        if role == "salesman" and (not customer or customer.assigned_salesman_id != user_id):
            skipped.append(_skip(application_id, app.batch_number, "无权操作"))
            continue

        checklist = build_material_checklist(db, app)
        if not checklist["is_complete"]:
            skipped.append(
                _skip(application_id, app.batch_number, f"缺少必传材料：{'、'.join(checklist['missing'])}")
            )
            continue

        app.status = target_status
        app.submitted_at = datetime.utcnow()
        app.institution_name = institution_name
        if not app.cycle_year:
            app.cycle_year = datetime.utcnow().year

        db.add(OperationLog(
            user_id=user_id,
            username=username,
            action="批量提交评审机构",
            resource_type="application",
            resource_id=app.id,
            new_value={
                "detail": f"报送机构: {institution_name}",
                "batch_number": app.batch_number,
            },
        ))

        # 通知：仅在客户有归属业务员时发送（业务员 + 全部管理员）
        if customer and customer.assigned_salesman_id:
            create_notification(
                db=db,
                user_id=customer.assigned_salesman_id,
                title="已提交评审机构",
                content=f"客户 {customer.name} 的申报批次 {app.batch_number} 已提交至评审机构",
                type="status_change",
                related_type="application",
                related_id=app.id,
            )
            for admin in db.query(User).filter(User.role == "admin").all():
                create_notification(
                    db=db,
                    user_id=admin.id,
                    title="批次已提交评审机构",
                    content=f"客户 {customer.name} 的申报批次 {app.batch_number} 已提交至评审机构",
                    type="status_change",
                    related_type="application",
                    related_id=app.id,
                )
        success += 1

    db.commit()
    return {
        "message": f"成功提交 {success} 个批次",
        "success": success,
        "skipped": skipped,
    }


@router.post("/remind")
async def batch_remind(
    application_ids: List[int] = Body(..., embed=True),
    message: str = Body("", embed=True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "salesman")),
):
    """批量催办：向批次所属客户的业务员发送催办通知。"""
    role = current_user.get("role")
    user_id = current_user.get("user_id") or current_user.get("id")
    custom_message = (message or "").strip()

    success = 0
    skipped = []

    for application_id in application_ids:
        app = (
            db.query(Application)
            .filter(Application.id == application_id, Application.is_deleted == False)  # noqa: E712
            .first()
        )
        if not app:
            skipped.append(_skip(application_id, None, "批次不存在"))
            continue

        customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
        if not customer or customer.is_deleted:
            skipped.append(_skip(application_id, app.batch_number, "客户不存在"))
            continue
        if role == "salesman" and customer.assigned_salesman_id != user_id:
            skipped.append(_skip(application_id, app.batch_number, "无权操作"))
            continue
        if not customer.assigned_salesman_id:
            skipped.append(_skip(application_id, app.batch_number, "客户无归属业务员"))
            continue

        content = custom_message or (
            f"客户 {customer.name} 的申报批次 {app.batch_number}（当前状态：{app.status}）需要尽快处理"
        )
        create_notification(
            db=db,
            user_id=customer.assigned_salesman_id,
            title="材料催办提醒",
            content=content,
            type="batch_remind",
            related_type="application",
            related_id=app.id,
        )
        success += 1

    db.commit()
    return {
        "message": f"已催办 {success} 个批次",
        "success": success,
        "skipped": skipped,
    }
