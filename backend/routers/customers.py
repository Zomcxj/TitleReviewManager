from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from database import get_db
from models import Customer, Application, User, Material, OperationLog
from schemas import (
    CustomerCreate, CustomerUpdate, CustomerResponse,
    ApplicationResponse,
)
from auth import get_current_user, require_role
from enums import CustomerSource
from datetime import datetime, timezone
import asyncio
import logging
import uuid
from utils.audit_logger import manual_audit_log
from utils.system_config import get_config
from storage import get_pinyin_initial, create_customer_directories, customer_dir, rename_customer_directory
from routers.notifications import create_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["客户管理"])


def _require_roles(*roles: str):
    """兼容 require_role 的签名差异（*args / List）与 async 工厂写法"""
    try:
        dep = require_role(*roles)
    except TypeError:
        dep = require_role(list(roles))
    if asyncio.iscoroutine(dep):
        dep = asyncio.run(dep)
    return dep


def _duplicate_phone_error(db: Session, phone: str, exclude_customer_id: int = None):
    """手机号查重。

    是否拦截由系统配置 reject_duplicate_phone 决定：默认为 0（不拦截），
    因为一个手机号可能是家属共用。仅当配置为真时才返回错误提示文案。
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
    """客户改名/换业务员后同步 NAS 目录：重命名目录并修正该客户材料的 file_path 前缀。"""
    year = customer.created_at.year if customer.created_at else datetime.utcnow().year
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
        # 用 outer join：客户从回收站恢复后，名下批次可能仍在回收站，
        # 此时客户本身应回到列表（状态显示为未知），而不是因 inner join 被隐藏
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
        # 统计该申请的材料数量
        materials_count = 0
        if app:
            materials_count = db.query(func.count(Material.id)).filter(Material.application_id == app.id).scalar() or 0
        item = CustomerResponse.model_validate(customer).model_dump()
        # 字段级权限：业务员看他人客户 / 审核员 → 证件号与手机号脱敏
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
    
    # 统一 join Customer 并排除软删除客户，避免软删除客户名下批次仍被统计
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
    """获取所有业务员列表（转让选择、客户列表业务员列展示）"""
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
    # 手机号查重（仅当系统配置 reject_duplicate_phone 为真时拦截）
    phone_error = _duplicate_phone_error(db, data.phone)
    if phone_error:
        raise HTTPException(status_code=400, detail=phone_error)
    customer = Customer(**data.model_dump())
    if not customer.source:
        customer.source = CustomerSource.OFFLINE.value
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

    # 身份证号唯一性预检
    if "id_number" in update_data and update_data["id_number"] != customer.id_number:
        dup = db.query(Customer).filter(
            Customer.id_number == update_data["id_number"],
            Customer.is_deleted == False,  # noqa: E712
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="该身份证号已存在")

    # 手机号唯一性预检（仅当系统配置 reject_duplicate_phone 为真时拦截）
    if "phone" in update_data and update_data["phone"] != customer.phone:
        phone_error = _duplicate_phone_error(db, update_data["phone"], exclude_customer_id=customer.id)
        if phone_error:
            raise HTTPException(status_code=400, detail=phone_error)

    # 记录目录同步所需的旧值（应用变更前）
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


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """软删除客户（移入回收站）。

    权限：admin / salesman（salesman 仅限自己名下的客户）。
    名下所有申报批次一并软删除，客户从归属中释放。
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

    # 已进入评审流程（提交评审机构审核及之后）的批次不允许删除客户
    REVIEW_STAGE_STATUSES = {"提交评审机构审核", "返修", "通过", "不通过"}
    if any(app.status in REVIEW_STAGE_STATUSES for app in applications):
        raise HTTPException(status_code=400, detail="该客户存在评审中的批次，无法删除")

    now = datetime.utcnow()
    customer.is_deleted = True
    customer.deleted_at = now
    # 释放客户归属，避免软删除记录仍占用归属/公海统计
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
    """转让客户给其他业务员"""
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

    # 同步 NAS 目录（换业务员后目录在新业务员名下）
    _sync_customer_directory(db, customer, old_name, old_pinyin, old_salesman.username if old_salesman else "")

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

    # 通知原业务员与新业务员
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

        # 同步 NAS 目录
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

        # 通知原业务员与新业务员
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
