from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import OperationLog, User
from schemas import OperationLogResponse, OperationLogListResponse
from datetime import datetime, timezone
from typing import Optional
from auth import get_current_user
import json
from io import BytesIO
from urllib.parse import quote

router = APIRouter(prefix="/api/audit", tags=["审计日志"])

# 单次导出上限，超出部分截断并在表尾注明
EXPORT_MAX_ROWS = 10000
# 单元格内 JSON 文本长度上限，避免 Excel 单元格过长
EXPORT_CELL_MAX_LEN = 1000


def _build_log_query(
    db: Session,
    action: Optional[str],
    resource_type: Optional[str],
    username: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
):
    """按筛选条件构造审计日志查询（列表接口与导出接口共用，保证口径一致）。"""
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

    return query


@router.get("/export")
async def export_operation_logs(
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    username: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """导出审计日志为 Excel（仅管理员，最多 10000 条）。"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以导出审计日志")

    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    query = _build_log_query(db, action, resource_type, username, start_date, end_date)
    total = query.count()
    logs = (
        query.order_by(desc(OperationLog.created_at))
        .limit(EXPORT_MAX_ROWS)
        .all()
    )

    def _serialize(value):
        if value is None:
            return ""
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
        return text[:EXPORT_CELL_MAX_LEN]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "操作审计日志"

    headers = [
        "ID", "操作人", "操作类型", "资源类型", "资源ID",
        "变更前", "变更后", "IP地址", "User-Agent", "操作时间",
    ]
    ws.append(headers)

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    for log in logs:
        ws.append([
            log.id,
            log.username or "",
            log.action or "",
            log.resource_type or "",
            log.resource_id if log.resource_id is not None else "",
            _serialize(log.old_value),
            _serialize(log.new_value),
            log.ip_address or "",
            log.user_agent or "",
            log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
        ])

    if total > EXPORT_MAX_ROWS:
        ws.append([f"（已截断，仅导出前 {EXPORT_MAX_ROWS} 条）"])

    widths = [8, 14, 28, 14, 10, 40, 40, 16, 30, 20]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = quote(f"操作审计日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", safe="")
    return Response(
        content=output.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"audit_logs.xlsx\"; filename*=UTF-8''{filename}",
        },
    )


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
    
    query = _build_log_query(db, action, resource_type, username, start_date, end_date)
    
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
