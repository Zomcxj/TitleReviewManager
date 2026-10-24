"""
Data isolation (by customer ownership)

Background: salesmen should only see data of their own customers. Isolation checks
used to be scattered across routers (materials.py had a local implementation;
reviews/feedback had none at all), which meant:
- Any logged-in user could query review records and agency feedback of any
  application (including return reasons and agency opinions)
- A salesman could see review details of other salesmen's customers

This module consolidates the checks into one reusable function; new query
endpoints can simply call it.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Application, Customer


def get_application_or_404(db: Session, application_id: int) -> Application:
    """Fetch an application; 404 if missing or soft-deleted"""
    app = db.query(Application).filter(
        Application.id == application_id,
        Application.is_deleted == False,  # noqa: E712
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    return app


def get_customer_of_application(db: Session, app: Application) -> Customer | None:
    """Fetch the customer owning the application"""
    if not app or not app.customer_id:
        return None
    return db.query(Customer).filter(Customer.id == app.customer_id).first()


def assert_can_access_customer(user: dict, customer: Customer | None, action: str = "查看") -> None:
    """Check whether the current user may access this customer's data.

    Rules:
    - admin / reviewer: unrestricted (reviewers must review across salesmen)
    - salesman: only their own customers
    - Missing customer: treated as no access (avoids probing existence via "customer deleted")
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
    """Check access by application ID; returns the application (404 if missing)"""
    app = get_application_or_404(db, application_id)
    customer = get_customer_of_application(db, app)
    assert_can_access_customer(user, customer, action)
    return app


def assert_can_access_material(db: Session, user: dict, material_id: int, action: str = "查看"):
    """Check access by material ID; returns (material, application, customer)"""
    from models import Material

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    app = get_application_or_404(db, material.application_id)
    customer = get_customer_of_application(db, app)
    assert_can_access_customer(user, customer, action)
    return material, app, customer
