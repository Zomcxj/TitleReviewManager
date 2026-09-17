"""
回收站（仅管理员）

- 列出各资源的软删除记录（customer / application / user）
- 恢复（is_deleted=False, deleted_at=None）
- 彻底删除（物理删除，带关联约束校验）
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from database import get_db
from models import Customer, Application, User, Material, Review, Feedback, PaymentRecord
from auth import require_role
from utils.audit_logger import manual_audit_log

router = APIRouter(prefix="/api/recycle-bin", tags=["回收站"])

VALID_TYPES = ("customer", "application", "user")


class RestoreRequest(BaseModel):
    resource_type: str
    id: int


def _log(db: Session, user: dict, action: str, resource_type: str, resource_id: int,
         old_value=None, new_value=None, request: Request = None):
    manual_audit_log(
        db=db,
        user_id=user.get("id"),
        username=user.get("username"),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        request=request,
    )


def _salesman_name(db: Session, salesman_id) -> str:
    if not salesman_id:
        return "未分配"
    u = db.query(User).filter(User.id == salesman_id).first()
    if not u:
        return "未分配"
    return u.real_name or u.username


def _customer_item(db: Session, c: Customer) -> dict:
    tail = (c.id_number or "")[-4:]
    detail = f"身份证 ****{tail}｜业务员 {_salesman_name(db, c.assigned_salesman_id)}"
    return {
        "resource_type": "customer",
        "id": c.id,
        "name": c.name,
        "deleted_at": c.deleted_at,
        "detail": detail,
    }


def _application_item(db: Session, a: Application) -> dict:
    customer = a.customer
    detail = f"客户 {customer.name if customer else '未知'}｜状态 {a.status}"
    return {
        "resource_type": "application",
        "id": a.id,
        "name": a.batch_number,
        "deleted_at": a.deleted_at,
        "detail": detail,
    }


def _user_item(u: User) -> dict:
    return {
        "resource_type": "user",
        "id": u.id,
        "name": u.username,
        "deleted_at": u.deleted_at,
        "detail": f"角色 {u.role}",
    }


# ---------- C1 列表 ----------

@router.get("/")
async def list_recycle_bin(
    resource_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    if resource_type and resource_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的资源类型，可选：{list(VALID_TYPES)}")

    items = []
    if resource_type in (None, "customer"):
        for c in db.query(Customer).filter(Customer.is_deleted == True).all():  # noqa: E712
            items.append(_customer_item(db, c))
    if resource_type in (None, "application"):
        for a in db.query(Application).filter(Application.is_deleted == True).all():  # noqa: E712
            items.append(_application_item(db, a))
    if resource_type in (None, "user"):
        for u in db.query(User).filter(User.is_deleted == True).all():  # noqa: E712
            items.append(_user_item(u))

    items.sort(key=lambda x: x["deleted_at"] or datetime.min, reverse=True)
    return {"items": items, "total": len(items)}


# ---------- C2 恢复 ----------

@router.post("/restore")
async def restore(
    data: RestoreRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    if data.resource_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的资源类型，可选：{list(VALID_TYPES)}")

    if data.resource_type == "customer":
        obj = db.query(Customer).filter(
            Customer.id == data.id, Customer.is_deleted == True  # noqa: E712
        ).first()
        if not obj:
            raise HTTPException(status_code=404, detail="记录不存在或未被删除")
        # 身份证号唯一性校验（排除自身）
        dup = db.query(Customer).filter(
            Customer.id_number == obj.id_number,
            Customer.id != obj.id,
            Customer.is_deleted == False,  # noqa: E712
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="存在相同身份证号的客户，无法恢复")
    elif data.resource_type == "application":
        obj = db.query(Application).filter(
            Application.id == data.id, Application.is_deleted == True  # noqa: E712
        ).first()
        if not obj:
            raise HTTPException(status_code=404, detail="记录不存在或未被删除")
    else:
        obj = db.query(User).filter(
            User.id == data.id, User.is_deleted == True  # noqa: E712
        ).first()
        if not obj:
            raise HTTPException(status_code=404, detail="记录不存在或未被删除")

    obj.is_deleted = False
    obj.deleted_at = None

    _log(
        db, user, "从回收站恢复", data.resource_type, obj.id,
        old_value={"is_deleted": True, "deleted_at": None},
        new_value={"is_deleted": False},
        request=request,
    )
    db.commit()
    return {"message": "已恢复"}


# ---------- C3 彻底删除 ----------

@router.delete("/purge/{resource_type}/{resource_id}")
async def purge(
    resource_type: str,
    resource_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    if resource_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的资源类型，可选：{list(VALID_TYPES)}")

    if resource_type == "customer":
        obj = db.query(Customer).filter(Customer.id == resource_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="记录不存在")
        if db.query(Application).filter(Application.customer_id == obj.id).first():
            raise HTTPException(status_code=400, detail="请先彻底删除该客户名下的申报批次")
        # 关联清理：跟进记录等
        from models import FollowUp
        db.query(FollowUp).filter(FollowUp.customer_id == obj.id).delete(synchronize_session=False)
        _log(db, user, "彻底删除", "customer", obj.id,
             old_value={"name": obj.name, "id_number": obj.id_number}, request=request)
        db.delete(obj)

    elif resource_type == "application":
        obj = db.query(Application).filter(Application.id == resource_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="记录不存在")
        material_ids = [
            row[0] for row in db.query(Material.id).filter(
                Material.application_id == obj.id).all()
        ]
        # 先删关联，再删主体（Review 同时挂 material 与 application）
        db.query(Review).filter(Review.application_id == obj.id).delete(synchronize_session=False)
        if material_ids:
            db.query(Review).filter(Review.material_id.in_(material_ids)).delete(synchronize_session=False)
        db.query(Material).filter(Material.application_id == obj.id).delete(synchronize_session=False)
        db.query(Feedback).filter(Feedback.application_id == obj.id).delete(synchronize_session=False)
        db.query(PaymentRecord).filter(PaymentRecord.application_id == obj.id).delete(synchronize_session=False)
        _log(db, user, "彻底删除", "application", obj.id,
             old_value={"batch_number": obj.batch_number}, request=request)
        db.delete(obj)

    else:
        obj = db.query(User).filter(User.id == resource_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="记录不存在")
        if db.query(Customer).filter(Customer.assigned_salesman_id == obj.id).first():
            raise HTTPException(status_code=400, detail="该用户名下仍有客户，无法彻底删除")
        _log(db, user, "彻底删除", "user", obj.id,
             old_value={"username": obj.username, "role": obj.role}, request=request)
        db.delete(obj)

    db.commit()
    return {"message": "已彻底删除"}
