from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.orm import Session
from database import get_db
from models import Customer, User, Application, OperationLog
from auth import get_current_user
from storage import get_pinyin_initial
import openpyxl
from io import BytesIO

router = APIRouter(prefix="/api/imports", tags=["批量导入"])


@router.post("/customers")
async def import_customers(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "salesman"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可导入")

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in ("xlsx", "xls"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")

    content = await file.read()
    wb = openpyxl.load_workbook(BytesIO(content), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="文件为空或仅含表头")

    headers = [str(h).strip() if h else "" for h in rows[0]]
    col_map = {h: i for i, h in enumerate(headers)}

    required = {"客户姓名", "身份证号"}
    missing = required - set(col_map.keys())
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少必需列：{', '.join(missing)}")

    results = {"total": 0, "success": 0, "errors": []}
    salesman_id = user.get("user_id") or user.get("id")

    for idx, row in enumerate(rows[1:], start=2):
        results["total"] += 1
        try:
            name = str(row[col_map["客户姓名"]]).strip()
            id_number = str(row[col_map["身份证号"]]).strip()
            id_number = id_number.replace("\t", "").replace(" ", "")
            if not name or not id_number:
                results["errors"].append(f"第{idx}行：姓名或身份证号为空")
                continue

            existing = db.query(Customer).filter(Customer.id_number == id_number).first()
            if existing:
                results["errors"].append(f"第{idx}行：身份证号已存在（{name}）")
                continue

            phone = str(row[col_map.get("手机号", -1)] or "").strip() if "手机号" in col_map else ""
            education = str(row[col_map.get("学历", -1)] or "").strip() if "学历" in col_map else ""
            current_title = str(row[col_map.get("现职称", -1)] or "").strip() if "现职称" in col_map else ""
            work_unit = str(row[col_map.get("工作单位", -1)] or "").strip() if "工作单位" in col_map else ""
            position = str(row[col_map.get("岗位", -1)] or "").strip() if "岗位" in col_map else ""

            customer = Customer(
                name=name,
                id_number=id_number,
                name_pinyin=get_pinyin_initial(name),
                phone=phone or None,
                education=education or None,
                current_title=current_title or None,
                work_unit=work_unit or None,
                position=position or None,
                assigned_salesman_id=salesman_id if user.get("role") == "salesman" else None,
            )
            db.add(customer)
            db.flush()
            results["success"] += 1
        except Exception as e:
            results["errors"].append(f"第{idx}行：{str(e)}")

    log = OperationLog(
        user_id=salesman_id,
        username=user.get("username", ""),
        action="批量导入客户",
        resource_type="customer",
        resource_id=0,
        new_value={"total": results["total"], "success": results["success"], "errors": len(results["errors"])},
    )
    db.add(log)
    db.commit()

    return {
        "message": f"导入完成：成功 {results['success']} / 共 {results['total']}",
        "success": results["success"],
        "total": results["total"],
        "errors": results["errors"],
    }
