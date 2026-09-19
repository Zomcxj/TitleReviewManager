"""
转化漏斗统计

业务价值：老板最关心的是"从咨询到拿证，各环节漏了多少"。
只有基础统计（客户总数、申报总数）回答不了这个问题。

漏斗阶段：
    建档（客户建立）
      → 材料准备中（有过材料上传）
      → 提交评审机构（进入 SUBMITTED 及之后）
      → 评审通过（APPROVED）

每阶段给出数量与相对上一阶段的转化率，并标出流失最多的环节。
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def get_conversion_funnel(db, days: Optional[int] = 180, salesman_id: Optional[int] = None) -> Dict:
    """计算申报转化漏斗。

    按**客户**口径统计（一个客户可能有多批次，取其在漏斗中最靠后的阶段）。
    """
    from sqlalchemy import func, distinct
    from models import Customer, Application, Material
    from enums import ApplicationStatus

    since = None
    if days:
        since = datetime.utcnow() - timedelta(days=days)

    # 1. 建档：符合条件的客户
    cust_q = db.query(Customer).filter(Customer.is_deleted == False)  # noqa: E712
    if since:
        cust_q = cust_q.filter(Customer.created_at >= since)
    if salesman_id:
        cust_q = cust_q.filter(Customer.assigned_salesman_id == salesman_id)
    total_customers = cust_q.count()
    customer_ids = {c.id for c in cust_q.with_entities(Customer.id).all()}

    if not customer_ids:
        return {
            "period_days": days,
            "stages": [
                {"name": "建档", "count": 0, "rate_from_prev": None, "rate_from_start": 100.0},
                {"name": "材料准备", "count": 0, "rate_from_prev": 0.0, "rate_from_start": 0.0},
                {"name": "提交机构", "count": 0, "rate_from_prev": 0.0, "rate_from_start": 0.0},
                {"name": "评审通过", "count": 0, "rate_from_prev": 0.0, "rate_from_start": 0.0},
            ],
            "drop_off": None,
            "total_customers": 0,
        }

    # 2. 材料准备：有材料上传的客户
    with_materials = {
        row[0] for row in (
            db.query(distinct(Application.customer_id))
            .join(Material, Material.application_id == Application.id)
            .filter(Application.customer_id.in_(customer_ids))
            .all()
        )
    }

    # 3. 提交机构：有批次进入过 SUBMITTED 及之后状态的客户
    post_submit_statuses = [
        ApplicationStatus.SUBMITTED.value,
        ApplicationStatus.REVISE.value,
        ApplicationStatus.APPROVED.value,
        ApplicationStatus.REJECTED.value,
    ]
    submitted = {
        row[0] for row in (
            db.query(distinct(Application.customer_id))
            .filter(
                Application.customer_id.in_(customer_ids),
                Application.submitted_at.isnot(None),
            )
            .all()
        )
    }
    # 兼容历史数据：没有 submitted_at 但状态已推进的也算
    submitted |= {
        row[0] for row in (
            db.query(distinct(Application.customer_id))
            .filter(
                Application.customer_id.in_(customer_ids),
                Application.status.in_(post_submit_statuses),
            )
            .all()
        )
    }

    # 4. 通过
    approved = {
        row[0] for row in (
            db.query(distinct(Application.customer_id))
            .filter(
                Application.customer_id.in_(customer_ids),
                Application.status == ApplicationStatus.APPROVED.value,
            )
            .all()
        )
    }

    stages_count = [total_customers, len(with_materials), len(submitted), len(approved)]
    names = ["建档", "材料准备", "提交机构", "评审通过"]

    stages = []
    prev = None
    for name, cnt in zip(names, stages_count):
        stages.append({
            "name": name,
            "count": cnt,
            "rate_from_prev": round(cnt / prev * 100, 1) if prev else None,
            "rate_from_start": round(cnt / total_customers * 100, 1) if total_customers else 0.0,
        })
        prev = cnt

    # 流失最多的环节
    drop_off = None
    max_lost = 0
    for i in range(1, len(stages_count)):
        lost = stages_count[i - 1] - stages_count[i]
        if lost > max_lost:
            max_lost = lost
            drop_off = {
                "from_stage": names[i - 1],
                "to_stage": names[i],
                "lost": lost,
                "lost_rate": round(lost / stages_count[i - 1] * 100, 1) if stages_count[i - 1] else 0.0,
            }

    return {
        "period_days": days,
        "total_customers": total_customers,
        "stages": stages,
        "drop_off": drop_off,
        "overall_rate": round(len(approved) / total_customers * 100, 1) if total_customers else 0.0,
    }
