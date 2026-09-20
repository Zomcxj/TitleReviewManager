"""
收费 / 合同 / 回款 / 证书管理

- 批次维度的合同与证书信息维护（admin / salesman）
- 回款明细登记，自动汇总 paid_amount 与 payment_status
- 财务总览与待收款提醒

权限约定：
  * 查询类（A1）登录用户即可
  * 维护类（A2/A3/A6）admin 全量，salesman 仅限自己名下客户
  * 删除回款（A4）、财务总览（A5）仅 admin
"""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user, require_role
from database import get_db
from enums import CertificateStatus, PaymentStatus
from models import Application, Customer, PaymentRecord, User
from schemas import (
    ApplicationFinanceUpdate,
    PaymentRecordCreate,
    PaymentRecordResponse,
)
from utils.audit_logger import manual_audit_log
from utils.timeutil import utcnow

router = APIRouter(prefix="/api/finance", tags=["收费与证书"])

PAYMENT_STATUS_VALUES = [s.value for s in PaymentStatus]
CERTIFICATE_STATUS_VALUES = [s.value for s in CertificateStatus]


# ---------- 内部工具 ----------

def _jsonable(value):
    """把 Decimal / datetime 转成可写入 JSON 列的值"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _get_application(db: Session, application_id: int) -> Application:
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    return app


def _check_owner_or_admin(app: Application, user: dict) -> None:
    """salesman 只能操作自己名下客户的批次"""
    if user.get("role") == "admin":
        return
    customer = app.customer
    if not customer or customer.assigned_salesman_id != user.get("id"):
        raise HTTPException(status_code=403, detail="只能操作自己名下客户的申报批次")


def _serialize_finance(db: Session, app: Application) -> dict:
    """统一的财务/证书信息结构（A1 返回体）"""
    records = (
        db.query(PaymentRecord)
        .filter(PaymentRecord.application_id == app.id)
        .order_by(PaymentRecord.id.desc())
        .all()
    )
    customer = app.customer
    return {
        "application_id": app.id,
        "batch_number": app.batch_number,
        "customer_id": app.customer_id,
        "customer_name": customer.name if customer else None,
        "contract_no": app.contract_no,
        "contract_signed_at": app.contract_signed_at,
        "fee_amount": float(app.fee_amount) if app.fee_amount is not None else None,
        "paid_amount": float(app.paid_amount or 0),
        "payment_status": app.payment_status,
        "payment_remark": app.payment_remark,
        "certificate_status": app.certificate_status,
        "certificate_no": app.certificate_no,
        "certificate_issued_at": app.certificate_issued_at,
        "certificate_delivered_at": app.certificate_delivered_at,
        "payment_records": [
            PaymentRecordResponse.model_validate(r).model_dump() for r in records
        ],
    }


def _recompute_payment(db: Session, app: Application) -> float:
    """按回款明细重新汇总 paid_amount 并推导 payment_status"""
    total = (
        db.query(func.coalesce(func.sum(PaymentRecord.amount), 0))
        .filter(PaymentRecord.application_id == app.id)
        .scalar()
    )
    total = float(total or 0)
    app.paid_amount = total

    if total <= 0:
        status = PaymentStatus.UNPAID.value
    elif app.fee_amount is not None and total >= float(app.fee_amount):
        status = PaymentStatus.PAID.value
    else:
        status = PaymentStatus.PARTIAL.value
    app.payment_status = status
    return total


# ---------- A1 查询 ----------

@router.get("/application/{application_id}")
async def get_application_finance(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    app = _get_application(db, application_id)
    # 数据隔离：合同金额与回款属敏感经营数据，业务员仅能看自己名下客户
    from utils.data_scope import assert_can_access_application
    assert_can_access_application(db, current_user, application_id)
    return _serialize_finance(db, app)


# ---------- A2 更新合同/证书 ----------

@router.put("/application/{application_id}")
async def update_application_finance(
    application_id: int,
    data: ApplicationFinanceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin", "salesman")),
):
    app = _get_application(db, application_id)
    _check_owner_or_admin(app, user)

    updates = data.model_dump(exclude_unset=True)

    # 两个状态列 NOT NULL：显式传 null 视为未提供，避免写入空值破坏约束
    for nullable_forbidden in ("payment_status", "certificate_status"):
        if updates.get(nullable_forbidden) is None:
            updates.pop(nullable_forbidden, None)

    if "payment_status" in updates and updates["payment_status"] not in PAYMENT_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的收费状态，可选：{PAYMENT_STATUS_VALUES}",
        )
    if "certificate_status" in updates and updates["certificate_status"] not in CERTIFICATE_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的证书状态，可选：{CERTIFICATE_STATUS_VALUES}",
        )

    old_value = {}
    new_value = {}
    for key, value in updates.items():
        before = getattr(app, key)
        if before != value:
            old_value[key] = _jsonable(before)
            new_value[key] = _jsonable(value)
        setattr(app, key, value)

    if old_value or new_value:
        manual_audit_log(
            db=db,
            user_id=user.get("id"),
            username=user.get("username"),
            action="更新收费/证书信息",
            resource_type="application",
            resource_id=app.id,
            old_value=old_value,
            new_value=new_value,
            request=request,
        )

    db.commit()
    db.refresh(app)
    return _serialize_finance(db, app)


# ---------- A3 登记回款 ----------

@router.post("/application/{application_id}/payments")
async def create_payment(
    application_id: int,
    data: PaymentRecordCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin", "salesman")),
):
    app = _get_application(db, application_id)
    _check_owner_or_admin(app, user)

    record = PaymentRecord(
        application_id=app.id,
        amount=data.amount,
        paid_at=data.paid_at or utcnow(),
        method=data.method,
        remark=data.remark,
        created_by_id=user.get("id"),
    )
    db.add(record)
    db.flush()

    total = _recompute_payment(db, app)

    manual_audit_log(
        db=db,
        user_id=user.get("id"),
        username=user.get("username"),
        action="登记回款",
        resource_type="application",
        resource_id=app.id,
        new_value={
            "payment_id": record.id,
            "amount": float(data.amount),
            "paid_amount": total,
            "payment_status": app.payment_status,
        },
        request=request,
    )

    db.commit()
    db.refresh(app)
    return _serialize_finance(db, app)


# ---------- A4 删除回款（仅 admin） ----------

@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    record = db.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="回款记录不存在")

    app = db.query(Application).filter(Application.id == record.application_id).first()
    old_value = {
        "payment_id": record.id,
        "amount": float(record.amount),
        "application_id": record.application_id,
    }
    db.delete(record)
    db.flush()

    new_paid = None
    if app:
        new_paid = _recompute_payment(db, app)

    manual_audit_log(
        db=db,
        user_id=user.get("id"),
        username=user.get("username"),
        action="删除回款记录",
        resource_type="application",
        resource_id=record.application_id,
        old_value=old_value,
        new_value={
            "paid_amount": new_paid,
            "payment_status": app.payment_status if app else None,
        },
        request=request,
    )

    db.commit()
    return {"message": "回款记录已删除"}


# ---------- A5 财务总览（仅 admin） ----------

@router.get("/summary")
async def finance_summary(
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    rows = (
        db.query(Application, Customer)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(Application.is_deleted == False)  # noqa: E712
        .all()
    )

    total_fee = 0.0
    total_paid = 0.0
    by_status = {}
    certificate_by_status = {}
    salesman_agg = {}

    for app, customer in rows:
        fee = float(app.fee_amount) if app.fee_amount is not None else 0.0
        paid = float(app.paid_amount or 0)
        total_fee += fee
        total_paid += paid

        p_status = app.payment_status or PaymentStatus.UNPAID.value
        by_status[p_status] = by_status.get(p_status, 0) + 1

        c_status = app.certificate_status or CertificateStatus.NOT_ISSUED.value
        certificate_by_status[c_status] = certificate_by_status.get(c_status, 0) + 1

        sid = customer.assigned_salesman_id
        entry = salesman_agg.setdefault(
            sid, {"salesman_id": sid, "name": None, "customer_ids": set(), "total_fee": 0.0, "total_paid": 0.0}
        )
        entry["customer_ids"].add(customer.id)
        entry["total_fee"] += fee
        entry["total_paid"] += paid

    # 补齐业务员姓名
    sids = [sid for sid in salesman_agg if sid is not None]
    name_map = {}
    if sids:
        for u in db.query(User).filter(User.id.in_(sids)).all():
            name_map[u.id] = u.real_name or u.username

    by_salesman = []
    for sid, entry in salesman_agg.items():
        by_salesman.append({
            "salesman_id": sid,
            "name": name_map.get(sid) or ("未分配" if sid is None else f"用户{sid}"),
            "customer_count": len(entry["customer_ids"]),
            "total_fee": round(entry["total_fee"], 2),
            "total_paid": round(entry["total_paid"], 2),
        })
    by_salesman.sort(key=lambda x: (x["salesman_id"] is None, -(x["total_fee"] or 0)))

    return {
        "total_fee": round(total_fee, 2),
        "total_paid": round(total_paid, 2),
        "total_unpaid": round(max(0.0, total_fee - total_paid), 2),
        "by_status": by_status,
        "by_salesman": by_salesman,
        "certificate_by_status": certificate_by_status,
    }


# ---------- A6 待收款提醒 ----------

@router.get("/pending")
async def pending_payments(
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin", "salesman")),
):
    query = (
        db.query(Application, Customer)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(
            Application.is_deleted == False,  # noqa: E712
            Application.fee_amount.isnot(None),
            Application.payment_status.in_([
                PaymentStatus.UNPAID.value,
                PaymentStatus.PARTIAL.value,
            ]),
        )
    )
    if user.get("role") == "salesman":
        query = query.filter(Customer.assigned_salesman_id == user.get("id"))

    rows = query.all()

    sids = {c.assigned_salesman_id for _, c in rows if c.assigned_salesman_id is not None}
    name_map = {}
    if sids:
        for u in db.query(User).filter(User.id.in_(sids)).all():
            name_map[u.id] = u.real_name or u.username

    items = []
    for app, customer in rows:
        fee = float(app.fee_amount) if app.fee_amount is not None else 0.0
        paid = float(app.paid_amount or 0)
        items.append({
            "application_id": app.id,
            "batch_number": app.batch_number,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "salesman_id": customer.assigned_salesman_id,
            "salesman_name": name_map.get(customer.assigned_salesman_id, "未分配"),
            "fee_amount": fee,
            "paid_amount": paid,
            "unpaid_amount": round(max(0.0, fee - paid), 2),
            "payment_status": app.payment_status,
            "created_at": app.created_at,
        })

    items.sort(key=lambda x: x["unpaid_amount"], reverse=True)
    return items[:100]
