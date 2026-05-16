from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from database import get_db
from models import Customer, Application, User, Material
from auth import get_current_user
from datetime import datetime, timezone
import openpyxl
from io import BytesIO

router = APIRouter(prefix="/api/exports", tags=["数据导出"])


@router.post("/customers")
async def export_customers(
    status: str = Query(None),
    keyword: str = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from sqlalchemy import or_
    
    query = db.query(Customer, Application).join(
        Application, Customer.id == Application.customer_id
    )
    
    if current_user.get("role") == "salesman":
        query = query.filter(Customer.assigned_salesman_id == current_user.get("id"))
    
    if status:
        query = query.filter(Application.status == status)
    
    if keyword:
        query = query.filter(
            or_(
                Customer.name.like(f"%{keyword}%"),
                Customer.id_number.like(f"%{keyword}%"),
                Customer.phone.like(f"%{keyword}%"),
                Customer.work_unit.like(f"%{keyword}%"),
            )
        )
    
    query = query.order_by(Application.id.desc())
    results = query.all()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "客户列表"
    
    headers = [
        "客户姓名", "身份证号", "手机号", "学历", "现职称", "获聘年份",
        "工作单位", "岗位", "专业年限", "申报批次", "当前状态", "创建时间",
    ]
    ws.append(headers)
    
    for customer, app in results:
        ws.append([
            customer.name,
            customer.id_number + "\t",
            customer.phone or "",
            customer.education or "",
            customer.current_title or "",
            customer.current_title_year or "",
            customer.work_unit or "",
            customer.position or "",
            customer.professional_years or "",
            app.batch_number if app else "",
            app.status if app else "",
            customer.created_at.strftime("%Y-%m-%d %H:%M") if customer.created_at else "",
        ])
    
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = (max_length + 2) if max_length < 50 else 50
        ws.column_dimensions[column].width = adjusted_width
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    from urllib.parse import quote
    filename = quote(f"客户列表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    
    return Response(
        content=output.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/applications")
async def export_applications(
    status: str = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    query = db.query(Application).join(Customer)
    
    if current_user.get("role") == "salesman":
        query = query.filter(Customer.assigned_salesman_id == current_user.get("id"))
    
    if status:
        query = query.filter(Application.status == status)
    
    query = query.order_by(Application.id.desc())
    applications = query.all()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "申报批次"
    
    headers = [
        "批次号", "客户姓名", "客户 ID 号", "申报状态", "创建时间", "更新时间",
    ]
    ws.append(headers)
    
    for app in applications:
        ws.append([
            app.batch_number,
            app.customer.name,
            app.customer.id_number + "\t",
            app.status,
            app.created_at.strftime("%Y-%m-%d %H:%M") if app.created_at else "",
            app.updated_at.strftime("%Y-%m-%d %H:%M") if app.updated_at else "",
        ])
    
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = (max_length + 2) if max_length < 50 else 50
        ws.column_dimensions[column].width = adjusted_width
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    from urllib.parse import quote
    filename = quote(f"申报批次_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    
    return Response(
        content=output.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
