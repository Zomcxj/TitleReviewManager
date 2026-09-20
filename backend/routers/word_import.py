import uuid
from contextlib import suppress
from io import BytesIO
from urllib.parse import quote

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Application, Customer, OperationLog
from storage import get_pinyin_initial

router = APIRouter(prefix="/api/word-import", tags=["Word导入"])


def _get_cell_text(cell) -> str:
    """提取单元格文本，去除空白"""
    return (cell.text or "").strip().replace("\n", "").replace("\r", "")


def _set_cell(cell, text: str, bold=False, size=10):
    """设置单元格内容和样式"""
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.name = "微软雅黑"
    run.bold = bold


@router.get("/template")
async def download_template(request: Request):
    """下载 Word 填报模板"""
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可下载模板")

    doc = Document()

    # 设置默认字体
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10)

    # 标题
    title = doc.add_heading("职称申报信息登记表", level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 说明
    doc.add_paragraph("请填写以下信息，填写完成后将此文件交给业务员上传系统。")
    doc.add_paragraph("")

    # 一、基本信息表格
    doc.add_heading("一、基本信息", level=2)

    fields = [
        ("姓名", ""),
        ("身份证号", ""),
        ("手机号", ""),
        ("学历", "（高中及以下/中专技校/大专/本科/硕士研究生/博士研究生）"),
        ("工作单位", ""),
        ("职务", ""),
        ("工作年限", "（数字，如：5）"),
    ]

    table = doc.add_table(rows=len(fields), cols=2, style="Table Grid")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, (label, hint) in enumerate(fields):
        _set_cell(table.cell(i, 0), label, bold=True, size=10)
        _set_cell(table.cell(i, 1), hint, size=10)
        # 设置第一列宽度
        table.cell(i, 0).width = Cm(4)
        table.cell(i, 1).width = Cm(12)

    doc.add_paragraph("")

    # 二、项目经历表格
    doc.add_heading("二、项目经历（可空，至少填一项）", level=2)

    headers = ["序号", "项目名称", "起始时间", "结束时间", "本人角色", "简要描述"]
    proj_table = doc.add_table(rows=4, cols=len(headers), style="Table Grid")
    proj_table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 表头
    for j, h in enumerate(headers):
        _set_cell(proj_table.cell(0, j), h, bold=True, size=9)

    # 预留 3 行空白
    for i in range(1, 4):
        _set_cell(proj_table.cell(i, 0), str(i), size=9)

    doc.add_paragraph("")
    doc.add_paragraph("填写说明：项目经历请如实填写，起止时间格式如 2022-03。")

    # 保存到内存
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    # RFC 5987: 中文文件名编码
    filename_encoded = quote("职称申报信息登记表.docx", safe='')
    ascii_name = "application_form.docx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{filename_encoded}'
        },
    )


@router.post("/parse")
async def parse_word(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """解析上传的 Word 文件，自动创建客户记录"""
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可操作")

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in ("docx",):
        raise HTTPException(status_code=400, detail="仅支持 .docx 文件")

    content = await file.read()
    try:
        doc = Document(BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败：{str(e)}") from e

    tables = doc.tables
    if len(tables) < 1:
        raise HTTPException(status_code=400, detail="文件中未找到表格，请使用系统提供的模板填写")

    # 解析第一个表格（基本信息）
    basic_table = tables[0]
    data = {}
    for row in basic_table.rows:
        if len(row.cells) >= 2:
            key = _get_cell_text(row.cells[0])
            val = _get_cell_text(row.cells[1])
            if key:
                data[key] = val

    # 验证必填字段
    name = data.get("姓名", "")
    id_number = data.get("身份证号", "")

    if not name:
        raise HTTPException(status_code=400, detail="缺少必填字段：姓名")
    if not id_number:
        raise HTTPException(status_code=400, detail="缺少必填字段：身份证号")

    id_number = id_number.replace("\t", "").replace(" ", "").replace("　", "")

    # 检查是否已存在
    existing = db.query(Customer).filter(Customer.id_number == id_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"身份证号 {id_number} 已存在（{existing.name}）")

    # 解析工作年限
    years_str = data.get("工作年限", "")
    professional_years = None
    if years_str:
        # 解析失败保持 None（字段非必填，格式不规范不应中断导入）
        with suppress(ValueError):
            professional_years = int(years_str.replace("年", "").strip())

    # 解析第二个表格（项目经历）
    projects = []
    if len(tables) >= 2:
        proj_table = tables[1]
        for i, row in enumerate(proj_table.rows):
            if i == 0:  # 跳过表头
                continue
            cells = [_get_cell_text(c) for c in row.cells]
            if len(cells) >= 6 and cells[1]:  # 有项目名称
                projects.append({
                    "name": cells[1],
                    "start_date": cells[2],
                    "end_date": cells[3],
                    "role": cells[4],
                    "description": cells[5],
                })

    # 创建客户
    salesman_id = user.get("user_id") or user.get("id")
    customer = Customer(
        name=name,
        id_number=id_number,
        name_pinyin=get_pinyin_initial(name),
        phone=data.get("手机号") or None,
        education=data.get("学历") or None,
        current_title=None,  # 不再从 Word 获取
        current_title_year=None,
        work_unit=data.get("工作单位") or None,
        position=data.get("职务") or None,
        professional_years=professional_years,
        project_experiences=str(projects) if projects else None,
        assigned_salesman_id=salesman_id,
    )
    db.add(customer)
    db.flush()

    # 创建默认申报批次
    app = Application(
        customer_id=customer.id,
        batch_number=f"BATCH-{uuid.uuid4().hex[:8].upper()}",
    )
    db.add(app)

    # 操作日志
    log = OperationLog(
        user_id=salesman_id,
        username=user.get("username", ""),
        action="Word导入客户",
        resource_type="customer",
        resource_id=customer.id,
        new_value={"detail": f"通过Word模板导入客户: {name}", "file": file.filename},
    )
    db.add(log)
    db.commit()

    return {
        "message": f"导入成功：{name}",
        "customer_id": customer.id,
        "batch_number": app.batch_number,
        "project_count": len(projects),
    }
