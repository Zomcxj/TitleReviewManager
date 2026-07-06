from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from database import get_db
from models import Customer, Application, User
from auth import get_current_user
from datetime import datetime, timezone
from routers.notifications import create_notification
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
            customer.sla_deadline = datetime.utcnow()
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
                    user_id=customer.assigned_salesman_id,
                    title="客户被释放",
                    content=f"你的客户 {customer.name} 已被释放到公海池",
                    type="batch_release",
                    related_type="customer",
                    related_id=customer.id,
                )
    
    db.commit()
    return {"message": f"成功释放 {updated_count} 个客户到公海池"}
