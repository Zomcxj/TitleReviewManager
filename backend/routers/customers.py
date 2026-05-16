from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, case
from sqlalchemy.sql import exists
from database import get_db
from models import Customer, Application, User, Material
from schemas import (
    CustomerCreate, CustomerUpdate, CustomerResponse,
    ApplicationCreate, ApplicationResponse,
)
from auth import get_current_user
from datetime import datetime, timezone
from utils.audit_logger import manual_audit_log
import uuid

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
        results.append({
            **CustomerResponse.model_validate(customer).model_dump(),
            "current_status": app.status if app else "未知",
            "application_id": app.id if app else None,
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
    
    status_rows = base_query.group_by(Application.status).all()
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
    db.add(customer)
    db.flush()
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
    db.commit()
    db.refresh(customer)
    return CustomerResponse.model_validate(customer)


@router.get("/self/{id_number}")
async def get_self_customer(id_number: str, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id_number == id_number).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return CustomerResponse.model_validate(customer)
