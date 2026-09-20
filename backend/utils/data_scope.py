"""
数据隔离（按客户归属）

背景：业务员只能看到自己名下客户的数据。此前隔离校验散落在各 router 里
（materials.py 有本地实现，reviews/feedback 完全没有），导致：
- 任何登录用户都能查任意批次的审核记录与机构反馈（含退回原因、机构意见）
- 业务员能看到他人客户的审核详情

这里统一成一个可复用的检查函数，新增查询接口时直接调用即可。
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Application, Customer


def get_application_or_404(db: Session, application_id: int) -> Application:
    """取批次，不存在或已软删除则 404"""
    app = db.query(Application).filter(
        Application.id == application_id,
        Application.is_deleted == False,  # noqa: E712
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    return app


def get_customer_of_application(db: Session, app: Application) -> Customer | None:
    """取批次所属客户"""
    if not app or not app.customer_id:
        return None
    return db.query(Customer).filter(Customer.id == app.customer_id).first()


def assert_can_access_customer(user: dict, customer: Customer | None, action: str = "查看") -> None:
    """校验当前用户是否有权访问该客户的数据。

    规则：
    - admin / reviewer：不限（审核员需要跨业务员审核）
    - salesman：仅自己名下客户
    - 客户不存在：视为无权（避免通过"客户已删除"探测存在性）
    """
    role = (user or {}).get("role")
    if role in ("admin", "reviewer"):
        return
    if role == "salesman":
        uid = (user or {}).get("user_id") or (user or {}).get("id")
        if not customer or customer.assigned_salesman_id != uid:
            raise HTTPException(status_code=403, detail=f"无权{action}该客户的数据")
        return
    raise HTTPException(status_code=403, detail="无权访问")


def assert_can_access_application(db: Session, user: dict, application_id: int, action: str = "查看") -> Application:
    """按批次 ID 校验访问权，返回批次对象（不存在时 404）"""
    app = get_application_or_404(db, application_id)
    customer = get_customer_of_application(db, app)
    assert_can_access_customer(user, customer, action)
    return app


def assert_can_access_material(db: Session, user: dict, material_id: int, action: str = "查看"):
    """按材料 ID 校验访问权，返回 (material, application, customer)"""
    from models import Material

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    app = get_application_or_404(db, material.application_id)
    customer = get_customer_of_application(db, app)
    assert_can_access_customer(user, customer, action)
    return material, app, customer
