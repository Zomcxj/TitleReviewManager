"""Customer progress self-service query (anonymous entry point).

Security design notes:
1. Both the full ID number and the last 4 digits of the phone number must be provided
   to query, preventing enumeration of customers by ID number alone.
2. Any mismatch returns the same unified 404 message, without distinguishing
   "ID not found" from "phone mismatch", to avoid information leakage.
3. Rate limiting per IP (at most 20 queries per 5 minutes), with counters stored in
   the database to support multi-worker deployments.
4. The response body contains progress info only; sensitive fields such as ID
   number / phone number / work unit are never returned.
"""


from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Application, Customer, Feedback, Material
from utils.login_guard import check_ip_rate_limit, record_attempt

router = APIRouter(prefix="/api/public-progress", tags=["进度查询"])

RATE_WINDOW_SECONDS = 300  # 5 minutes
MAX_QUERIES_PER_WINDOW = 20


# ---------- Progress stage mapping ----------
# The fixed 4 stages shown by the frontend (the order is the progression order)
PROGRESS_STEPS = ["初次申报", "完成资料", "提交评审机构审核", "通过"]

# Mapping rules from business status to stage index (the exact status values are the
# Chinese keys of STATUS_TO_STAGE_INDEX below):
#   Supplement materials / Second application belong to the first-round preparation
#   stage, equivalent to Initial application (index 0)
#   Materials complete means the materials are ready, index 1
#   Submitted to review agency / Return for revision / Not passed have all entered the
#   agency phase, equivalent to Submitted to review agency (index 2)
#     (Not passed reached the agency phase but did not pass, so the Passed stage is
#     still not achieved)
#   Passed, index 3
STATUS_TO_STAGE_INDEX = {
    "初次申报": 0,
    "资料补充": 0,
    "二次申报": 0,
    "完成资料": 1,
    "提交评审机构审核": 2,
    "返修": 2,
    "不通过": 2,
    "通过": 3,
}


class ProgressQuery(BaseModel):
    id_number: str = Field(..., min_length=1, max_length=18)
    phone_tail: str = Field(..., min_length=1, max_length=10)


def build_progress_steps(current_status: str | None) -> list[dict]:
    """Generate stage completion in the fixed order."""
    current_index = STATUS_TO_STAGE_INDEX.get(current_status or "", 0)
    return [
        {"name": name, "done": current_index >= index}
        for index, name in enumerate(PROGRESS_STEPS)
    ]


def build_materials_summary(db: Session, application_id: int) -> dict:
    """Material audit status summary: total / passed / flagged / pending."""
    materials = db.query(Material).filter(Material.application_id == application_id).all()
    summary = {"total": len(materials), "passed": 0, "flagged": 0, "pending": 0}
    for material in materials:
        if material.audit_status == "已通过":
            summary["passed"] += 1
        elif material.audit_status == "已标记问题":
            summary["flagged"] += 1
        else:
            summary["pending"] += 1
    return summary


def build_latest_feedback(db: Session, application_id: int) -> str | None:
    """The latest agency feedback content (None if absent)."""
    feedback = (
        db.query(Feedback)
        .filter(Feedback.application_id == application_id)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .first()
    )
    return feedback.content if feedback else None


@router.get("/status")
async def public_progress_status():
    """Health probe: lets the frontend check whether this self-service entry is available."""
    return {"available": True}


@router.post("/query")
async def query_progress(
    data: ProgressQuery,
    request: Request,
    db: Session = Depends(get_db),
):
    from utils.request_context import get_client_ip
    client_ip = get_client_ip(request)
    # Rate limiting goes through the database (counters shared across workers); reuses the
    # login-attempt table, distinguished by scope
    check_ip_rate_limit(db, f"progress:{client_ip}", MAX_QUERIES_PER_WINDOW, RATE_WINDOW_SECONDS)
    record_attempt(db, f"progress:{client_ip}")
    db.commit()

    not_found = HTTPException(
        status_code=404,
        detail="未查询到申报记录，请核对身份证号与手机号后4位",
    )

    id_number = (data.id_number or "").strip()
    phone_tail = (data.phone_tail or "").strip()
    # Must be exactly the last 4 digits of the phone number, otherwise treated as a mismatch
    # (providing only 1-2 digits would weaken the check)
    if not id_number or len(phone_tail) != 4 or not phone_tail.isdigit():
        raise not_found

    customer = (
        db.query(Customer)
        .filter(Customer.id_number == id_number, Customer.is_deleted == False)  # noqa: E712
        .first()
    )
    if not customer:
        raise not_found
    # Last-4-digits check: fails when phone is empty
    phone = customer.phone or ""
    if not phone or not phone.endswith(phone_tail):
        raise not_found

    applications = (
        db.query(Application)
        .filter(Application.customer_id == customer.id, Application.is_deleted == False)  # noqa: E712
        .order_by(Application.id.desc())
        .all()
    )

    items = []
    for app in applications:
        items.append(
            {
                "batch_number": app.batch_number,
                "professional_category": app.professional_category,
                "title_level": app.title_level,
                "status": app.status,
                "cycle_year": app.cycle_year,
                "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
                "updated_at": app.updated_at.isoformat() if app.updated_at else None,
                "progress_steps": build_progress_steps(app.status),
                "materials_summary": build_materials_summary(db, app.id),
                "latest_feedback": build_latest_feedback(db, app.id),
            }
        )

    return {"customer_name": customer.name, "items": items}
