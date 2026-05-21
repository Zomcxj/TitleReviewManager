from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import OperationLog, User
from schemas import OperationLogResponse, OperationLogListResponse
from datetime import datetime, timezone
from typing import Optional
from auth import get_current_user

router = APIRouter(prefix="/api/audit", tags=["审计日志"])


@router.get("", response_model=OperationLogListResponse)
@router.get("/logs", response_model=OperationLogListResponse)
async def get_operation_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    username: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以查看审计日志")
    
    query = db.query(OperationLog)
    
    if action:
        query = query.filter(OperationLog.action.like(f"%{action}%"))
    if resource_type:
        query = query.filter(OperationLog.resource_type == resource_type)
    if username:
        query = query.filter(OperationLog.username.like(f"%{username}%"))
    if start_date:
        query = query.filter(OperationLog.created_at >= start_date)
    if end_date:
        query = query.filter(OperationLog.created_at <= end_date)
    
    total = query.count()
    logs = (
        query.order_by(desc(OperationLog.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    return {
        "items": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/logs/resource/{resource_type}/{resource_id}")
async def get_resource_logs(
    resource_type: str,
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以查看审计日志")
    
    logs = (
        db.query(OperationLog)
        .filter(
            OperationLog.resource_type == resource_type,
            OperationLog.resource_id == resource_id,
        )
        .order_by(desc(OperationLog.created_at))
        .limit(50)
        .all()
    )
    
    return {"items": logs, "total": len(logs)}
