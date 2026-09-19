"""
材料退回原因统计

业务价值：哪些材料最常被退回，是提升通过率的关键线索。
统计后可反推给业务员做预防（例如"业绩成果"退回率最高，
就该在上传前重点检查），也能评估业务员材料准备质量。
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


def get_rejection_stats(
    db,
    days: Optional[int] = 90,
    salesman_id: Optional[int] = None,
) -> Dict:
    """材料退回原因统计。

    Args:
        days: 统计最近多少天（None 表示全部）
        salesman_id: 只看某业务员名下客户（None 表示全部）

    Returns:
        {
          "total_reviews": 审核总数,
          "total_rejected": 退回总数,
          "reject_rate": 退回率,
          "by_category": [{category, rejected, total, rate}],   # 按材料类别
          "by_issue_type": [{issue_type, count, rate}],          # 按问题类型
          "by_salesman": [{salesman_id, name, rejected, total, rate}],  # 按业务员
          "trend": [{date, rejected}],                           # 近 N 天趋势
        }
    """
    from sqlalchemy import func
    from models import Review, Material, Application, Customer, User

    since = None
    if days:
        since = datetime.utcnow() - timedelta(days=days)

    # 基础查询：材料级审核记录（排除 application 级的批量审核记录）
    base = (
        db.query(Review, Material, Application, Customer)
        .join(Material, Review.material_id == Material.id)
        .join(Application, Review.application_id == Application.id)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(Review.result == "退回", Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        base = base.filter(Review.created_at >= since)
    if salesman_id:
        base = base.filter(Customer.assigned_salesman_id == salesman_id)

    rejected_rows = base.all()

    # 审核总数（含通过）用于算退回率
    total_q = (
        db.query(func.count(Review.id))
        .join(Material, Review.material_id == Material.id)
        .join(Application, Review.application_id == Application.id)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        total_q = total_q.filter(Review.created_at >= since)
    if salesman_id:
        total_q = total_q.filter(Customer.assigned_salesman_id == salesman_id)
    total_reviews = total_q.scalar() or 0
    total_rejected = len(rejected_rows)

    # 按材料类别
    cat_rejected: Dict[str, int] = {}
    cat_total: Dict[str, int] = {}
    all_q = (
        db.query(Material.category, func.count(Review.id))
        .join(Material, Review.material_id == Material.id)
        .join(Application, Review.application_id == Application.id)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        all_q = all_q.filter(Review.created_at >= since)
    if salesman_id:
        all_q = all_q.filter(Customer.assigned_salesman_id == salesman_id)
    for cat, cnt in all_q.group_by(Material.category).all():
        cat_total[cat] = cnt
    for r, m, a, c in rejected_rows:
        cat_rejected[m.category] = cat_rejected.get(m.category, 0) + 1

    by_category = []
    for cat, total in sorted(cat_total.items(), key=lambda x: -x[1]):
        rej = cat_rejected.get(cat, 0)
        by_category.append({
            "category": cat,
            "total": total,
            "rejected": rej,
            "rate": round(rej / total * 100, 1) if total else 0.0,
        })

    # 按问题类型
    issue_count: Dict[str, int] = {}
    for r, m, a, c in rejected_rows:
        key = r.issue_type or "未分类"
        issue_count[key] = issue_count.get(key, 0) + 1
    by_issue_type = [
        {"issue_type": k, "count": v, "rate": round(v / total_rejected * 100, 1) if total_rejected else 0.0}
        for k, v in sorted(issue_count.items(), key=lambda x: -x[1])
    ]

    # 按业务员
    sales_rejected: Dict[int, int] = {}
    sales_total: Dict[int, int] = {}
    for r, m, a, c in rejected_rows:
        sid = c.assigned_salesman_id
        if sid:
            sales_rejected[sid] = sales_rejected.get(sid, 0) + 1

    sales_total_q = (
        db.query(Customer.assigned_salesman_id, func.count(Review.id))
        .join(Application, Application.customer_id == Customer.id)
        .join(Review, Review.application_id == Application.id)
        .join(Material, Review.material_id == Material.id)
        .filter(Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        sales_total_q = sales_total_q.filter(Review.created_at >= since)
    for sid, cnt in sales_total_q.group_by(Customer.assigned_salesman_id).all():
        if sid:
            sales_total[sid] = cnt

    name_map = {u.id: (u.real_name or u.username) for u in db.query(User).all()}
    by_salesman = []
    for sid, total in sorted(sales_total.items(), key=lambda x: -sales_rejected.get(x[0], 0)):
        rej = sales_rejected.get(sid, 0)
        by_salesman.append({
            "salesman_id": sid,
            "name": name_map.get(sid, f"用户{sid}"),
            "total": total,
            "rejected": rej,
            "rate": round(rej / total * 100, 1) if total else 0.0,
        })

    # 趋势（近 30 天，或 days 内最多 30 天）
    trend_days = min(days or 30, 30)
    trend_start = datetime.utcnow() - timedelta(days=trend_days - 1)
    daily: Dict[str, int] = {}
    for r, m, a, c in rejected_rows:
        created = r.created_at
        if created is None:
            continue
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        if created >= trend_start.replace(hour=0, minute=0, second=0, microsecond=0):
            key = created.strftime("%Y-%m-%d")
            daily[key] = daily.get(key, 0) + 1

    trend = []
    for i in range(trend_days):
        d = (trend_start + timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({"date": d, "rejected": daily.get(d, 0)})

    return {
        "period_days": days,
        "total_reviews": total_reviews,
        "total_rejected": total_rejected,
        "reject_rate": round(total_rejected / total_reviews * 100, 1) if total_reviews else 0.0,
        "by_category": by_category,
        "by_issue_type": by_issue_type,
        "by_salesman": by_salesman,
        "trend": trend,
    }
