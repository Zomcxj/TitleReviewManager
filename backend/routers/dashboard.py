from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Customer, Application, User
from auth import get_current_user
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/dashboard", tags=["数据看板"])


@router.get("/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
    base_query = db.query(Application)
    if user_role == "salesman":
        base_query = base_query.join(Customer).filter(Customer.assigned_salesman_id == user_id)
        customers_query = db.query(Customer).filter(Customer.assigned_salesman_id == user_id, Customer.is_public == False)
    else:
        customers_query = db.query(Customer).filter(Customer.is_public == False)
    
    total_customers = customers_query.count()
    
    total_applications = base_query.count()
    
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_new = base_query.filter(Application.created_at >= today).count()
    
    this_week_start = today - timedelta(days=today.weekday())
    week_new = base_query.filter(Application.created_at >= this_week_start).count()
    
    by_status_query = db.query(Application.status, func.count(Application.id))
    if user_role == "salesman":
        by_status_query = by_status_query.join(Customer).filter(Customer.assigned_salesman_id == user_id)
    by_status = by_status_query.group_by(Application.status).all()
    status_distribution = {row[0]: row[1] for row in by_status}
    
    return {
        "total_customers": total_customers,
        "total_applications": total_applications,
        "today_new": today_new,
        "week_new": week_new,
        "status_distribution": status_distribution,
    }


@router.get("/trend")
async def get_trend_data(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
    base_query = db.query(Application)
    if user_role == "salesman":
        base_query = base_query.join(Customer).filter(Customer.assigned_salesman_id == user_id)
    
    end_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=days - 1)
    
    daily_data = (
        base_query.filter(Application.created_at >= start_date)
        .with_entities(
            func.date(Application.created_at).label('date'),
            func.count(Application.id).label('count')
        )
        .group_by(func.date(Application.created_at))
        .all()
    )
    
    result = {}
    for row in daily_data:
        date_str = row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0])
        result[date_str] = row[1]
    
    trend = []
    current = start_date
    while current <= end_date:
        date_str = current.strftime('%Y-%m-%d')
        trend.append({
            "date": date_str,
            "count": result.get(date_str, 0),
        })
        current += timedelta(days=1)
    
    return {"trend": trend}


@router.get("/performance")
async def get_performance_ranking(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    salesmen = (
        db.query(User)
        .filter(User.role == "salesman")
        .with_entities(
            User.id,
            User.real_name,
            User.username,
        )
        .all()
    )
    
    ranking = []
    for s in salesmen:
        customer_count = db.query(Customer).filter(
            Customer.assigned_salesman_id == s.id,
            Customer.is_public == False
        ).count()
        
        approved_count = (
            db.query(Application)
            .join(Customer)
            .filter(
                Customer.assigned_salesman_id == s.id,
                Application.status == "通过"
            )
            .count()
        )
        
        ranking.append({
            "id": s.id,
            "name": s.real_name or s.username,
            "customer_count": customer_count,
            "approved_count": approved_count,
        })
    
    ranking.sort(key=lambda x: x["approved_count"], reverse=True)
    
    return {"ranking": ranking[:limit]}
