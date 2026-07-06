from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from database import get_db
from models import Customer, Application, User, Material
from schemas import (
    CustomerCreate, CustomerUpdate, CustomerResponse,
    ApplicationCreate, ApplicationResponse,
)
from auth import get_current_user
from datetime import datetime, timezone, timedelta
import uuid
from utils.audit_logger import manual_audit_log
from storage import get_pinyin_initial, create_customer_directories, customer_dir
from routers.notifications import create_notification

router = APIRouter(prefix="/api/customers", tags=["客户管理"])


@router.get("/")
async def list_customers(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    status: str = None,
    keyword: str = None,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    
    latest_app_subq = (
        db.query(
            Application.customer_id,
            func.max(Application.id).label("max_id")
        )
        .group_by(Application.customer_id)
        .subquery()
    )
    
    base_query = (
        db.query(Customer, Application)
        .join(latest_app_subq, Customer.id == latest_app_subq.c.customer_id)
        .join(Application, Application.id == latest_app_subq.c.max_id)
    )
    
    if user.get("role") == "salesman":
        base_query = base_query.filter(Customer.assigned_salesman_id == user.get("id"))
    
    if status:
        base_query = base_query.filter(Application.status == status)
    
    if keyword:
        base_query = base_query.filter(
            or_(
                Customer.name.like(f"%{keyword}%"),
                Customer.id_number.like(f"%{keyword}%"),
                Customer.phone.like(f"%{keyword}%"),
                Customer.work_unit.like(f"%{keyword}%"),
            )
        )
    
    total = base_query.count()
    items = base_query.offset((page - 1) * page_size).limit(page_size).all()
    
    results = []
    for customer, app in items:
        # 统计该申请的材料数量
        materials_count = 0
        if app:
            materials_count = db.query(func.count(Material.id)).filter(Material.application_id == app.id).scalar() or 0
        results.append({
            **CustomerResponse.model_validate(customer).model_dump(),
            "current_status": app.status if app else "未知",
            "application_id": app.id if app else None,
            "materials_count": materials_count,
        })
    
    return {"items": results, "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
async def get_stats(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    
    base_query = db.query(Application)
    if user.get("role") == "salesman":
        base_query = base_query.join(Customer).filter(Customer.assigned_salesman_id == user.get("id"))
    elif user.get("role") == "reviewer":
        base_query = base_query.filter(Application.status.in_(["提交评审机构审核", "返修", "通过", "不通过"]))
    
    from sqlalchemy import func
    status_rows = db.query(Application.status, func.count(Application.id)).group_by(Application.status).all()
    status_counts = {row[0]: row[1] for row in status_rows}
    
    all_statuses = ["初次申报", "资料补充", "完成资料", "提交评审机构审核", "返修", "通过", "不通过", "二次申报"]
    for s in all_statuses:
        if s not in status_counts:
            status_counts[s] = 0
    
    total_query = db.query(func.count(Application.id))
    if user.get("role") == "salesman":
        total_query = total_query.join(Customer).filter(Customer.assigned_salesman_id == user.get("id"))
    total = total_query.scalar()
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_query = db.query(func.count(Application.id)).filter(Application.created_at >= today_start)
    if user.get("role") == "salesman":
        today_query = today_query.join(Customer).filter(Customer.assigned_salesman_id == user.get("id"))
    today_new = today_query.scalar()
    
    return {"by_status": status_counts, "total": total, "today_new": today_new}


@router.get("/salesmen")
async def list_salesmen(request: Request, db: Session = Depends(get_db)):
    """获取所有业务员列表（用于转让选择）"""
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="无权访问")

    salesmen = db.query(User).filter(User.role == "salesman").order_by(User.id).all()
    return [{"id": s.id, "username": s.username, "real_name": s.real_name or s.username} for s in salesmen]


@router.get("/self/{id_number}")
async def get_self_customer(id_number: str, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id_number == id_number).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return CustomerResponse.model_validate(customer)


@router.get("/{customer_id}", response_model=dict)
async def get_customer(customer_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    applications = db.query(Application).filter(
        Application.customer_id == customer_id
    ).order_by(Application.id.desc()).all()
    apps_data = []
    for app in applications:
        materials = db.query(Material).filter(Material.application_id == app.id).all()
        apps_data.append({
            **ApplicationResponse.model_validate(app).model_dump(),
            "materials_count": len(materials),
        })
    return {
        **CustomerResponse.model_validate(customer).model_dump(),
        "applications": apps_data,
    }


@router.post("/", response_model=CustomerResponse)
async def create_customer(
    data: CustomerCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    existing = db.query(Customer).filter(Customer.id_number == data.id_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="该身份证号已存在")
    customer = Customer(**data.model_dump())
    customer.name_pinyin = get_pinyin_initial(customer.name)
    db.add(customer)
    db.flush()
    # 创建 NAS 目录模板
    salesman = db.query(User).filter(User.id == customer.assigned_salesman_id).first() if customer.assigned_salesman_id else None
    create_customer_directories(
        year=customer.created_at.year if customer.created_at else datetime.utcnow().year,
        salesman_name=salesman.username if salesman else "未分配",
        customer_name=customer.name,
        initial=customer.name_pinyin or get_pinyin_initial(customer.name),
    )
    app = Application(
        customer_id=customer.id,
        batch_number=f"BATCH-{uuid.uuid4().hex[:8].upper()}",
    )
    db.add(app)
    db.flush()
    manual_audit_log(
        db=db,
        user_id=user.get("id"),
        username=user.get("username"),
        action="CREATE",
        resource_type="customer",
        resource_id=customer.id,
        new_value={"name": customer.name, "id_number": customer.id_number, "batch_number": app.batch_number},
        request=request,
    )
    db.commit()
    db.refresh(customer)
    return CustomerResponse.model_validate(customer)


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    
    old_data = {
        "name": customer.name,
        "phone": customer.phone,
        "education": customer.education,
        "work_unit": customer.work_unit,
        "position": customer.position,
    }
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(customer, key, value)
    if "name" in update_data:
        customer.name_pinyin = get_pinyin_initial(customer.name)
        update_data["name_pinyin"] = customer.name_pinyin
    
    db.flush()
    manual_audit_log(
        db=db,
        user_id=user.get("id"),
        username=user.get("username"),
        action="UPDATE",
        resource_type="customer",
        resource_id=customer_id,
        old_value=old_data,
        new_value=update_data,
        request=request,
    )
    # 发送通知
    title = "客户信息变更"
    content = f"客户 {customer.name} 的信息已被 {user.get('username')} 修改"
    if customer.assigned_salesman_id:
        create_notification(
            db=db,
            user_id=customer.assigned_salesman_id,
            title=title,
            content=content,
            type="status_change",
            related_type="customer",
            related_id=customer_id,
        )
    admins = db.query(User).filter(User.role == "admin").all()
    for admin in admins:
        create_notification(
            db=db,
            user_id=admin.id,
            title=title,
            content=content,
            type="status_change",
            related_type="customer",
            related_id=customer_id,
        )
    db.commit()
    db.refresh(customer)
    return CustomerResponse.model_validate(customer)


@router.put("/{customer_id}/transfer")
async def transfer_customer(
    customer_id: int,
    request: Request,
    salesman_id: int = None,
    db: Session = Depends(get_db),
):
    """转让客户给其他业务员"""
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可操作")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    if not salesman_id:
        raise HTTPException(status_code=400, detail="请选择目标业务员")

    target = db.query(User).filter(User.id == salesman_id, User.role == "salesman").first()
    if not target:
        raise HTTPException(status_code=400, detail="目标业务员不存在")

    old_salesman_id = customer.assigned_salesman_id
    customer.assigned_salesman_id = salesman_id

    # 操作日志
    from models import OperationLog
    log = OperationLog(
        user_id=user.get("id"),
        username=user.get("username"),
        action="转让客户",
        resource_type="customer",
        resource_id=customer.id,
        old_value={"assigned_salesman_id": old_salesman_id},
        new_value={"assigned_salesman_id": salesman_id, "target_name": target.real_name},
    )
    db.add(log)
    db.commit()

    return {"message": f"已转让给 {target.real_name}"}


@router.post("/batch-transfer")
async def batch_transfer_customers(
    request: Request,
    data: dict = Body(...),
    db: Session = Depends(get_db),
):
    """批量转让客户给其他业务员"""
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作批量转让")

    customer_ids = data.get("customer_ids", [])
    salesman_id = data.get("salesman_id")

    if not customer_ids:
        raise HTTPException(status_code=400, detail="请选择要转让的客户")
    if not salesman_id:
        raise HTTPException(status_code=400, detail="请选择目标业务员")

    target = db.query(User).filter(User.id == salesman_id, User.role == "salesman").first()
    if not target:
        raise HTTPException(status_code=400, detail="目标业务员不存在")

    customers = db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
    count = 0
    for c in customers:
        old_id = c.assigned_salesman_id
        c.assigned_salesman_id = salesman_id
        from models import OperationLog
        log = OperationLog(
            user_id=user.get("id"),
            username=user.get("username"),
            action="批量转让客户",
            resource_type="customer",
            resource_id=c.id,
            old_value={"assigned_salesman_id": old_id},
            new_value={"assigned_salesman_id": salesman_id, "target_name": target.real_name},
        )
        db.add(log)
        count += 1

    db.commit()
    return {"message": f"已转让 {count} 位客户给 {target.real_name}", "count": count}
