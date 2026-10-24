import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth import get_current_user, require_role
from database import get_db
from enums import CustomerSource
from models import Application, Customer, Material, OperationLog, User
from routers.notifications import create_notification
from schemas import (
    ApplicationResponse,
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
)
from storage import create_customer_directories, customer_dir, get_pinyin_initial, rename_customer_directory
from utils.audit_logger import manual_audit_log
from utils.system_config import get_config
from utils.timeutil import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["客户管理"])


def _require_roles(*roles: str):
    """Handle require_role signature differences (*args / List) and async factory variants"""
    try:
        dep = require_role(*roles)
    except TypeError:
        dep = require_role(list(roles))
    if asyncio.iscoroutine(dep):
        dep = asyncio.run(dep)
    return dep


def _duplicate_phone_error(db: Session, phone: str, exclude_customer_id: int = None):
    """Duplicate phone check.

    Whether to block is decided by the system config reject_duplicate_phone:
    0 by default (no blocking), since a phone number may be shared by family
    members. The error message is returned only when the config is enabled.
    """
    if not phone:
        return None
    if not get_config(db, "reject_duplicate_phone"):
        return None
    q = db.query(Customer).filter(
        Customer.phone == phone,
        Customer.is_deleted == False,  # noqa: E712
    )
    if exclude_customer_id is not None:
        q = q.filter(Customer.id != exclude_customer_id)
    dup = q.first()
    if not dup:
        return None
    tail = (dup.id_number or "")[-4:]
    return f"该手机号已被客户 {dup.name}（身份证尾号 {tail}）使用"


def _sync_customer_directory(db: Session, customer: Customer, old_name: str, old_pinyin: str, old_salesman_username: str = ""):
    """Sync the NAS directory after a customer rename/salesman change: rename the directory and fix the file_path prefix of the customer's materials."""
    year = customer.created_at.year if customer.created_at else utcnow().year
    old_rel = customer_dir(
        year=year,
        salesman_name=old_salesman_username or "未分配",
        customer_name=old_name,
        initial=old_pinyin or get_pinyin_initial(old_name),
    )
    new_salesman = db.query(User).filter(User.id == customer.assigned_salesman_id).first() if customer.assigned_salesman_id else None
    new_rel = customer_dir(
        year=year,
        salesman_name=new_salesman.username if new_salesman else "",
        customer_name=customer.name,
        initial=customer.name_pinyin or get_pinyin_initial(customer.name),
    )
    if old_rel == new_rel:
        return
    if not rename_customer_directory(old_rel, new_rel):
        logger.warning(f"客户 {customer.id} 目录同步跳过：{old_rel} 不存在或重命名失败")
        return
    old_prefix = old_rel + "/"
    materials = (
        db.query(Material)
        .join(Application, Material.application_id == Application.id)
        .filter(Application.customer_id == customer.id)
        .all()
    )
    for m in materials:
        path = (m.file_path or "").replace("\\", "/")
        if path.startswith(old_prefix):
            m.file_path = new_rel + "/" + path[len(old_prefix):]


@router.get("/")
async def list_customers(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
        .filter(Application.is_deleted == False)  # noqa: E712
        .group_by(Application.customer_id)
        .subquery()
    )
    
    base_query = (
        db.query(Customer, Application)
        # Use outer join: after a customer is restored from the recycle bin, its batches
        # may still be in the recycle bin; the customer itself should return to the list
        # (status shown as unknown) instead of being hidden by an inner join
        .outerjoin(latest_app_subq, Customer.id == latest_app_subq.c.customer_id)
        .outerjoin(Application, Application.id == latest_app_subq.c.max_id)
        .filter(Customer.is_deleted == False)  # noqa: E712
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
        # Count materials for this application
        materials_count = 0
        if app:
            materials_count = db.query(func.count(Material.id)).filter(Material.application_id == app.id).scalar() or 0
        item = CustomerResponse.model_validate(customer).model_dump()
        # Field-level permissions: salesmen viewing others' customers / reviewers → mask ID number and phone
        from utils.masking import apply_customer_masking
        apply_customer_masking(item, user, customer)
        results.append({
            **item,
            "current_status": app.status if app else "未知",
            "application_id": app.id if app else None,
            "materials_count": materials_count,
        })
    
    return {"items": results, "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
async def get_stats(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    
    # Join Customer and exclude soft-deleted customers so batches under soft-deleted customers are not counted
    base_query = (
        db.query(Application)
        .join(Customer, Customer.id == Application.customer_id)
        .filter(
            Application.is_deleted == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
        )
    )
    if user.get("role") == "salesman":
        base_query = base_query.filter(Customer.assigned_salesman_id == user.get("id"))
    elif user.get("role") == "reviewer":
        base_query = base_query.filter(Application.status.in_(["提交评审机构审核", "返修", "通过", "不通过"]))

    status_rows = base_query.with_entities(Application.status, func.count(Application.id)).group_by(Application.status).all()
    status_counts = {row[0]: row[1] for row in status_rows}

    all_statuses = ["初次申报", "资料补充", "完成资料", "提交评审机构审核", "返修", "通过", "不通过", "二次申报"]
    for s in all_statuses:
        if s not in status_counts:
            status_counts[s] = 0

    total = base_query.with_entities(func.count(Application.id)).scalar()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_new = base_query.filter(Application.created_at >= today_start).with_entities(func.count(Application.id)).scalar()
    
    return {"by_status": status_counts, "total": total, "today_new": today_new}


@router.get("/salesmen")
async def list_salesmen(request: Request, db: Session = Depends(get_db)):
    """List all salesmen (for transfer selection and the salesman column in the customer list)"""
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman", "reviewer"):
        raise HTTPException(status_code=403, detail="无权访问")

    salesmen = db.query(User).filter(User.role == "salesman").order_by(User.id).all()
    return [{"id": s.id, "username": s.username, "real_name": s.real_name or s.username} for s in salesmen]


@router.get("/{customer_id}", response_model=dict)
async def get_customer(customer_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.is_deleted == False,  # noqa: E712
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    if user.get("role") == "salesman" and customer.assigned_salesman_id != user.get("id"):
        raise HTTPException(status_code=403, detail="只能查看自己名下的客户")
    applications = db.query(Application).filter(
        Application.customer_id == customer_id,
        Application.is_deleted == False,  # noqa: E712
    ).order_by(Application.id.desc()).all()
    apps_data = []
    for app in applications:
        materials = db.query(Material).filter(Material.application_id == app.id).all()
        apps_data.append({
            **ApplicationResponse.model_validate(app).model_dump(),
            "materials_count": len(materials),
        })
    detail = CustomerResponse.model_validate(customer).model_dump()
    from utils.masking import apply_customer_masking
    apply_customer_masking(detail, user, customer)
    return {
        **detail,
        "applications": apps_data,
    }


@router.post("/", response_model=CustomerResponse)
async def create_customer(
    data: CustomerCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可创建客户")
    existing = db.query(Customer).filter(
        Customer.id_number == data.id_number,
        Customer.is_deleted == False,  # noqa: E712
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该身份证号已存在")
    # Duplicate phone check (blocked only when the system config reject_duplicate_phone is enabled)
    phone_error = _duplicate_phone_error(db, data.phone)
    if phone_error:
        raise HTTPException(status_code=400, detail=phone_error)
    customer = Customer(**data.model_dump())
    if not customer.source:
        customer.source = CustomerSource.OFFLINE.value
    customer.name_pinyin = get_pinyin_initial(customer.name)
    db.add(customer)
    db.flush()
    # Create the NAS directory template
    salesman = db.query(User).filter(User.id == customer.assigned_salesman_id).first() if customer.assigned_salesman_id else None
    create_customer_directories(
        year=customer.created_at.year if customer.created_at else utcnow().year,
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
    user: dict = Depends(_require_roles("admin", "salesman")),
):
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.is_deleted == False,  # noqa: E712
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    if user.get("role") == "salesman" and customer.assigned_salesman_id != user.get("id"):
        raise HTTPException(status_code=403, detail="只能修改自己名下的客户")

    update_data = data.model_dump(exclude_unset=True)

    # ID number uniqueness pre-check
    if "id_number" in update_data and update_data["id_number"] != customer.id_number:
        dup = db.query(Customer).filter(
            Customer.id_number == update_data["id_number"],
            Customer.is_deleted == False,  # noqa: E712
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="该身份证号已存在")

    # Phone uniqueness pre-check (blocked only when the system config reject_duplicate_phone is enabled)
    if "phone" in update_data and update_data["phone"] != customer.phone:
        phone_error = _duplicate_phone_error(db, update_data["phone"], exclude_customer_id=customer.id)
        if phone_error:
            raise HTTPException(status_code=400, detail=phone_error)

    # Capture old values needed for directory sync (before applying changes)
    old_name = customer.name
    old_pinyin = customer.name_pinyin
    old_salesman = customer.assigned_salesman
    old_salesman_username = old_salesman.username if old_salesman else ""

    old_data = {
        "name": customer.name,
        "phone": customer.phone,
        "education": customer.education,
        "work_unit": customer.work_unit,
        "position": customer.position,
    }

    for key, value in update_data.items():
        setattr(customer, key, value)
    if "name" in update_data:
        customer.name_pinyin = get_pinyin_initial(customer.name)
        update_data["name_pinyin"] = customer.name_pinyin

    db.flush()
    _sync_customer_directory(db, customer, old_name, old_pinyin, old_salesman_username)
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
    # Send notifications
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


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Soft delete a customer (move to the recycle bin).

    Permissions: admin / salesman (salesman limited to their own customers).
    All application batches under the customer are soft deleted together, and the
    customer is released from assignment.
    """
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可删除客户")

    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.is_deleted == False,  # noqa: E712
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    if user.get("role") == "salesman" and customer.assigned_salesman_id != user.get("id"):
        raise HTTPException(status_code=403, detail="只能删除自己名下的客户")

    applications = db.query(Application).filter(
        Application.customer_id == customer_id,
        Application.is_deleted == False,  # noqa: E712
    ).all()

    # Batches already in review (submitted to institution and beyond) block customer deletion
    REVIEW_STAGE_STATUSES = {"提交评审机构审核", "返修", "通过", "不通过"}
    if any(app.status in REVIEW_STAGE_STATUSES for app in applications):
        raise HTTPException(status_code=400, detail="该客户存在评审中的批次，无法删除")

    now = utcnow()
    customer.is_deleted = True
    customer.deleted_at = now
    # Release the customer assignment so soft-deleted records do not skew assignment/public pool statistics
    customer.assigned_salesman_id = None
    customer.is_public = False

    for app in applications:
        app.is_deleted = True
        app.deleted_at = now

    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="删除客户",
        resource_type="customer",
        resource_id=customer.id,
        old_value={"name": customer.name, "application_count": len(applications)},
        new_value={"detail": f"删除客户: {customer.name}, 批次数量: {len(applications)}"},
    )
    db.add(log)
    db.commit()
    return {"message": "客户已移入回收站"}


@router.put("/{customer_id}/transfer")
async def transfer_customer(
    customer_id: int,
    request: Request,
    salesman_id: int = None,
    db: Session = Depends(get_db),
):
    """Transfer the customer to another salesman"""
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可操作")

    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.is_deleted == False,  # noqa: E712
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    if not salesman_id:
        raise HTTPException(status_code=400, detail="请选择目标业务员")

    target = db.query(User).filter(User.id == salesman_id, User.role == "salesman").first()
    if not target:
        raise HTTPException(status_code=400, detail="目标业务员不存在")

    old_salesman_id = customer.assigned_salesman_id
    old_salesman = customer.assigned_salesman
    old_name = customer.name
    old_pinyin = customer.name_pinyin

    customer.assigned_salesman_id = salesman_id

    # Sync the NAS directory (after the change the directory lives under the new salesman)
    _sync_customer_directory(db, customer, old_name, old_pinyin, old_salesman.username if old_salesman else "")

    # Operation log
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

    # Notify the previous and new salesmen
    if old_salesman_id and old_salesman_id != salesman_id:
        create_notification(
            db=db,
            user_id=old_salesman_id,
            title="客户调出",
            content=f"客户 {customer.name} 已被调出给 {target.real_name or target.username}",
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

    return {"message": f"已转让给 {target.real_name}"}


@router.post("/batch-transfer")
async def batch_transfer_customers(
    request: Request,
    data: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Batch transfer customers to another salesman"""
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

    customers = db.query(Customer).filter(
        Customer.id.in_(customer_ids),
        Customer.is_deleted == False,  # noqa: E712
    ).all()
    count = 0
    for c in customers:
        old_id = c.assigned_salesman_id
        old_salesman = c.assigned_salesman
        old_name = c.name
        old_pinyin = c.name_pinyin

        c.assigned_salesman_id = salesman_id

        # Sync the NAS directory
        _sync_customer_directory(db, c, old_name, old_pinyin, old_salesman.username if old_salesman else "")

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

        # Notify the previous and new salesmen
        if old_id and old_id != salesman_id:
            create_notification(
                db=db,
                user_id=old_id,
                title="客户调出",
                content=f"客户 {c.name} 已被调出给 {target.real_name or target.username}",
                type="batch_assign",
                related_type="customer",
                related_id=c.id,
            )
        create_notification(
            db=db,
            user_id=salesman_id,
            title="客户分配",
            content=f"你被分配了新客户 {c.name}",
            type="batch_assign",
            related_type="customer",
            related_id=c.id,
        )
        count += 1

    db.commit()
    return {"message": f"已转让 {count} 位客户给 {target.real_name}", "count": count}
