from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import OperationLog, User
from schemas import OperationLogResponse, OperationLogListResponse
from datetime import datetime, timezone
from typing import Optional
from auth import get_current_user
import json
import os
import tempfile
from urllib.parse import quote

router = APIRouter(prefix="/api/audit", tags=["审计日志"])

# 单次导出上限，超出部分截断并在表尾注明
EXPORT_MAX_ROWS = 10000
# 单元格内 JSON 文本长度上限，避免 Excel 单元格过长
EXPORT_CELL_MAX_LEN = 1000

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# 流式读取临时文件的块大小
STREAM_CHUNK_SIZE = 64 * 1024
# 数据库流式游标每次预取的记录数
YIELD_PER = 500
# 固定列宽：write_only 模式无法在写完后遍历 ws.columns 计算
EXPORT_COLUMN_WIDTHS = [8, 14, 28, 14, 10, 40, 40, 16, 30, 20]
# 审计导出表头（write_only 模式需用 WriteOnlyCell 逐格设置样式）
EXPORT_HEADERS = [
    "ID", "操作人", "操作类型", "资源类型", "资源ID",
    "变更前", "变更后", "IP地址", "User-Agent", "操作时间",
]


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _iter_file(path, chunk_size=STREAM_CHUNK_SIZE):
    """分块读取临时文件，正常结束或客户端中途断开都在 finally 里删除临时文件。"""
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        _safe_remove(path)


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
    """导出审计日志为 Excel（仅管理员，最多 10000 条）。

    使用 openpyxl write_only 模式 + SQLAlchemy yield_per 流式游标，
    避免一次性把全部日志读入内存；工作簿落盘到临时文件后分块返回。
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以导出审计日志")

    import openpyxl
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    query = _build_log_query(db, action, resource_type, username, start_date, end_date)
    # 多取 1 行即可判断是否被截断，省掉一次 count 查询
    logs = (
        query.order_by(desc(OperationLog.created_at))
        .limit(EXPORT_MAX_ROWS + 1)
        .yield_per(YIELD_PER)
    )

    def _serialize(value):
        if value is None:
            return ""
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
        return text[:EXPORT_CELL_MAX_LEN]

    def _build(ws):
        # write_only 模式：列宽须在写数据前设置，且不能用 ws[1] 遍历单元格
        for i, width in enumerate(EXPORT_COLUMN_WIDTHS, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_cells = []
        for title in EXPORT_HEADERS:
            cell = WriteOnlyCell(ws, value=title)
            cell.font = header_font
            cell.fill = header_fill
            header_cells.append(cell)
        ws.append(header_cells)

        written = 0
        truncated = False
        for log in logs:
            if written >= EXPORT_MAX_ROWS:
                truncated = True
                continue
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
            written += 1

        if truncated:
            ws.append([f"（已截断，仅导出前 {EXPORT_MAX_ROWS} 条）"])

    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx", prefix="audit_export_")
    os.close(fd)
    try:
        wb = openpyxl.Workbook(write_only=True)
        ws = wb.create_sheet(title="操作审计日志")
        _build(ws)
        wb.save(tmp_path)
    except Exception:
        _safe_remove(tmp_path)
        raise

    filename = quote(f"操作审计日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", safe="")
    return StreamingResponse(
        _iter_file(tmp_path),
        media_type=EXCEL_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename=\"audit_logs.xlsx\"; filename*=UTF-8''{filename}",
        },
        background=BackgroundTask(_safe_remove, tmp_path),
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
