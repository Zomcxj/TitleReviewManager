from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc
from database import get_db
from models import Customer, User, FollowUp, Application
from schemas import CustomerResponse
from auth import get_current_user
from datetime import datetime, timezone, timedelta
from routers.notifications import create_notification
from utils.system_config import get_config

router = APIRouter(prefix="/api/public-pool", tags=["公海池"])


@router.get("", response_model=dict)
@router.get("/", response_model=dict)
async def list_public_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
    query = db.query(Customer).filter(
        Customer.is_public == True,  # noqa: E712
        Customer.is_deleted == False,  # noqa: E712
    )
    
    if keyword:
        query = query.filter(
            or_(
                Customer.name.like(f"%{keyword}%"),
                Customer.phone.like(f"%{keyword}%"),
                Customer.work_unit.like(f"%{keyword}%"),
            )
        )
    
    total = query.count()
    customers = (
        query.order_by(desc(Customer.public_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    results = []
    for c in customers:
        last_app = db.query(Application).filter(
            Application.customer_id == c.id,
            Application.is_deleted == False,  # noqa: E712
        ).order_by(desc(Application.id)).first()
        
        item = CustomerResponse.model_validate(c).model_dump()
        # 公海客户尚未归属，除管理员外一律脱敏（避免批量抓取证件号）
        from utils.masking import apply_customer_masking
        apply_customer_masking(item, current_user, c)
        results.append({
            **item,
            "current_status": last_app.status if last_app else None,
            "days_in_pool": (datetime.utcnow() - c.public_at).days if c.public_at else 0,
        })
    
    return {"items": results, "total": total, "page": page, "page_size": page_size}


@router.post("/claim/{customer_id}")
async def claim_customer(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
    if user_role not in ["salesman", "admin"]:
        raise HTTPException(status_code=403, detail="只有业务员可以领取客户")
    
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.is_deleted == False,  # noqa: E712
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    
    if not customer.is_public:
        raise HTTPException(status_code=400, detail="客户不在公海池")
    
    current_salesman_count = db.query(Customer).filter(
        Customer.assigned_salesman_id == user_id,
        Customer.is_public == False,  # noqa: E712
        Customer.is_deleted == False,  # noqa: E712
    ).count()
    
    # 持有上限由系统配置 pool_claim_limit 驱动（默认 50）
    claim_limit = get_config(db, "pool_claim_limit")
    if current_salesman_count >= claim_limit:
        raise HTTPException(status_code=400, detail=f"每人最多持有 {claim_limit} 个客户")
    
    old_salesman_id = customer.assigned_salesman_id
    customer.assigned_salesman_id = user_id
    customer.is_public = False
    customer.public_at = None
    customer.last_follow_up_at = datetime.utcnow()
    # 分配后 SLA 时长由系统配置 sla_hours_after_assign 驱动（默认 24 小时）
    sla_hours = get_config(db, "sla_hours_after_assign")
    customer.sla_deadline = datetime.utcnow() + timedelta(hours=sla_hours)
    
    db.commit()
    
    if old_salesman_id:
        create_notification(
            db=db,
            user_id=old_salesman_id,
            title="客户被领取",
            content=f"你的客户 {customer.name} 已被业务员领取",
            type="pool_claim",
            related_type="customer",
            related_id=customer.id,
        )
    
    return {"message": "领取成功", "customer_id": customer.id}


@router.post("/release/{customer_id}")
async def release_customer(
    customer_id: int,
    reason: str = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.is_deleted == False,  # noqa: E712
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    
    if customer.assigned_salesman_id != user_id and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权释放该客户")
    
    customer.assigned_salesman_id = None
    customer.is_public = True
    customer.public_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": "已释放到公海池"}


@router.get("/stats")
async def get_pool_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    total_in_pool = db.query(Customer).filter(
        Customer.is_public == True,  # noqa: E712
        Customer.is_deleted == False,  # noqa: E712
    ).count()
    
    today_claims = db.query(Customer).filter(
        Customer.is_public == False,  # noqa: E712
        Customer.is_deleted == False,  # noqa: E712
        Customer.public_at >= datetime.utcnow() - timedelta(days=1)
    ).count()
    
    overdue = db.query(Customer).filter(
        Customer.sla_deadline < datetime.utcnow(),
        Customer.is_public == False,  # noqa: E712
        Customer.is_deleted == False,  # noqa: E712
        Customer.assigned_salesman_id.isnot(None)
    ).count()
    
    expiring_soon = db.query(Customer).filter(
        Customer.sla_deadline.between(
            datetime.utcnow(),
            datetime.utcnow() + timedelta(hours=12)
        ),
        Customer.is_public == False,  # noqa: E712
        Customer.is_deleted == False,  # noqa: E712
        Customer.assigned_salesman_id.isnot(None)
    ).count()
    
    return {
        "total_in_pool": total_in_pool,
        "today_claims": today_claims,
        "overdue": overdue,
        "expiring_soon": expiring_soon,
    }
