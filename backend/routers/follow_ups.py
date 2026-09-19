from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import FollowUp, Customer, User
from schemas import FollowUpResponse, FollowUpCreate
from auth import get_current_user
from datetime import datetime
from typing import List
from routers.notifications import create_notification

router = APIRouter(prefix="/api/follow-ups", tags=["跟进记录"])


@router.get("/customer/{customer_id}", response_model=List[FollowUpResponse])
async def get_customer_follow_ups(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    # 数据隔离：业务员只能查看自己名下客户的跟进记录
    from utils.data_scope import assert_can_access_customer
    assert_can_access_customer(current_user, customer)

    follow_ups = (
        db.query(FollowUp)
        .filter(FollowUp.customer_id == customer_id)
        .order_by(desc(FollowUp.created_at))
        .all()
    )
    
    results = []
    for fu in follow_ups:
        user = db.query(User).filter(User.id == fu.user_id).first()
        results.append({
            **FollowUpResponse.model_validate(fu).model_dump(),
            "username": user.username if user else None,
        })
    
    return results


@router.post("/", response_model=FollowUpResponse)
async def create_follow_up(
    data: FollowUpCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 仅业务员/管理员可创建跟进记录（审核员返回 403）
    if current_user.get("role") not in ("salesman", "admin"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可创建跟进记录")
    customer = db.query(Customer).filter(Customer.id == data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    
    follow_up = FollowUp(
        customer_id=data.customer_id,
        user_id=current_user.get("id"),
        content=data.content,
        follow_up_type=data.follow_up_type,
        next_follow_up_at=data.next_follow_up_at,
    )
    
    db.add(follow_up)
    db.flush()
    
    # 更新客户最后跟进时间（SLA 自动回收机制的依赖）
    customer.last_follow_up_at = datetime.utcnow()
    
    if data.next_follow_up_at:
        salesman_id = customer.assigned_salesman_id
        # 创建者就是该客户的归属业务员时不给自己发通知
        if salesman_id and salesman_id != current_user.get("id"):
            create_notification(
                db=db,
                user_id=salesman_id,
                title="跟进提醒",
                content=f"客户 {customer.name} 需要在 {data.next_follow_up_at.strftime('%m-%d %H:%M')} 进行跟进",
                type="follow_up_reminder",
                related_type="customer",
                related_id=customer.id,
            )
    
    db.commit()
    db.refresh(follow_up)
    
    return FollowUpResponse.model_validate(follow_up)


@router.delete("/{follow_up_id}")
async def delete_follow_up(
    follow_up_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    follow_up = db.query(FollowUp).filter(FollowUp.id == follow_up_id).first()
    if not follow_up:
        raise HTTPException(status_code=404, detail="跟进记录不存在")
    # 仅记录创建者本人或管理员可删除
    if follow_up.user_id != current_user.get("id") and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅记录创建者或管理员可删除跟进记录")
    
    db.delete(follow_up)
    db.commit()
    
    return {"message": "删除成功"}


@router.get("/schedule")
async def get_follow_up_schedule(
    scope: str = Query("today", description="today | overdue | week"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """待跟进日程（今天/逾期/未来一周）。

    业务员仅自己名下客户；admin/reviewer 可见全部。
    """
    if scope not in ("today", "overdue", "week"):
        raise HTTPException(status_code=400, detail="scope 只能是 today / overdue / week")
    from utils.follow_up_schedule import get_pending_follow_ups
    return get_pending_follow_ups(db, current_user, scope)


@router.get("/summary")
async def get_follow_up_summary_endpoint(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """待跟进汇总（用于工作台卡片与侧边提醒）"""
    from utils.follow_up_schedule import get_follow_up_summary
    return get_follow_up_summary(db, current_user)
