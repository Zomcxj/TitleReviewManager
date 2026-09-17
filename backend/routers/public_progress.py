"""客户进度自助查询（匿名入口）

安全设计要点：
1. 必须同时提供「完整身份证号」+「手机号后 4 位」才能查询，防止仅凭身份证号枚举客户。
2. 任一不匹配统一返回 404 同一文案，不区分"身份证不存在"与"手机号不匹配"，避免信息泄露。
3. 按 IP 内存限流（每 5 分钟最多 20 次）。
4. 响应体只包含进度信息，绝不返回身份证号 / 手机号 / 工作单位等敏感字段。
"""

import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Application, Customer, Feedback, Material

router = APIRouter(prefix="/api/public-progress", tags=["进度查询"])

# ---------- 限流：模块级内存字典，按 IP 记录查询时间戳 ----------
_QUERY_ATTEMPTS: Dict[str, List[float]] = {}
RATE_WINDOW_SECONDS = 300  # 5 分钟
MAX_QUERIES_PER_WINDOW = 20


def check_query_rate_limit(ip: str) -> None:
    """超过窗口内最大查询次数则抛 429。"""
    now = time.time()
    if ip not in _QUERY_ATTEMPTS:
        _QUERY_ATTEMPTS[ip] = []
    _QUERY_ATTEMPTS[ip] = [t for t in _QUERY_ATTEMPTS[ip] if now - t < RATE_WINDOW_SECONDS]
    if len(_QUERY_ATTEMPTS[ip]) >= MAX_QUERIES_PER_WINDOW:
        raise HTTPException(status_code=429, detail="查询过于频繁，请稍后再试")


def record_query(ip: str) -> None:
    _QUERY_ATTEMPTS.setdefault(ip, []).append(time.time())


# ---------- 进度阶段映射 ----------
# 前端展示的固定 4 个阶段（顺序即推进顺序）
PROGRESS_STEPS = ["初次申报", "完成资料", "提交评审机构审核", "通过"]

# 业务状态 -> 阶段索引 的映射规则：
#   "资料补充" / "二次申报" 属于首轮准备阶段，等同"初次申报"（索引 0）
#   "完成资料" 即资料齐备，索引 1
#   "提交评审机构审核" / "返修" / "不通过" 均已进入机构环节，等同"提交评审机构审核"（索引 2）
#     （"不通过" 到了机构环节但未通过，故 "通过" 阶段仍未达成）
#   "通过" 索引 3
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


def build_progress_steps(current_status: Optional[str]) -> List[dict]:
    """按固定顺序生成阶段完成情况。"""
    current_index = STATUS_TO_STAGE_INDEX.get(current_status or "", 0)
    return [
        {"name": name, "done": current_index >= index}
        for index, name in enumerate(PROGRESS_STEPS)
    ]


def build_materials_summary(db: Session, application_id: int) -> dict:
    """材料审核状态统计：总数 / 已通过 / 已标记问题 / 待审核。"""
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


def build_latest_feedback(db: Session, application_id: int) -> Optional[str]:
    """最近一条机构反馈内容（无则 None）。"""
    feedback = (
        db.query(Feedback)
        .filter(Feedback.application_id == application_id)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .first()
    )
    return feedback.content if feedback else None


@router.get("/status")
async def public_progress_status():
    """健康探针：供前端探测该自助查询入口是否可用。"""
    return {"available": True}


@router.post("/query")
async def query_progress(
    data: ProgressQuery,
    request: Request,
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    check_query_rate_limit(client_ip)
    record_query(client_ip)

    not_found = HTTPException(
        status_code=404,
        detail="未查询到申报记录，请核对身份证号与手机号后4位",
    )

    id_number = (data.id_number or "").strip()
    phone_tail = (data.phone_tail or "").strip()
    # 必须为完整手机号后 4 位数字，否则视为不匹配（避免只提供 1~2 位削弱校验强度）
    if not id_number or len(phone_tail) != 4 or not phone_tail.isdigit():
        raise not_found

    customer = (
        db.query(Customer)
        .filter(Customer.id_number == id_number, Customer.is_deleted == False)  # noqa: E712
        .first()
    )
    if not customer:
        raise not_found
    # 手机号后 4 位校验：phone 为空则不通过
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
