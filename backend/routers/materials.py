from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import get_db
from models import Material, Application, Customer, User, OperationLog
from schemas import MaterialResponse, MaterialCategory, AuditStatus
from auth import get_current_user
from datetime import datetime
from storage import save_file, read_file, delete_file as storage_delete, list_files as storage_list, customer_dir, get_pinyin_initial
import os as _os
from urllib.parse import quote

router = APIRouter(prefix="/api/applications/{application_id}/materials", tags=["材料管理"])

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 50 * 1024 * 1024

WRITE_ROLES = {"admin", "salesman"}


def require_write_role(user: dict):
    if user.get("role") not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="仅业务员和管理员可操作")


def _get_customer_dir(customer: Customer) -> str:
    year = customer.created_at.year if customer.created_at else datetime.utcnow().year
    salesman = ""
    if customer.assigned_salesman:
        salesman = customer.assigned_salesman.username or ""
    return customer_dir(
        year=year,
        salesman_name=salesman,
        customer_name=customer.name,
        initial=customer.name_pinyin or get_pinyin_initial(customer.name),
    )


@router.get("/")
async def list_materials(
    application_id: int,
    request: Request,
    keyword: str = None,
    category: str = None,
    audit_status: str = None,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    customer = db.query(Customer).filter(Customer.id == app.customer_id).first()

    q = db.query(Material).filter(Material.application_id == application_id)
    if keyword:
        q = q.filter(Material.filename.like(f"%{keyword}%"))
    if category:
        q = q.filter(Material.category == category)
    if audit_status:
        q = q.filter(Material.audit_status == audit_status)
    materials = q.order_by(Material.category, Material.version).all()

    db_list = [MaterialResponse.model_validate(m).model_dump() for m in materials]
    rel = _get_customer_dir(customer) if customer else ""
    tree = storage_list(rel) if rel else []
    return {"items": db_list, "tree": tree}


@router.post("/")
async def upload_material(
    application_id: int,
    request: Request,
    category: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    require_write_role(user)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    valid_categories = [c.value for c in MaterialCategory]
    if category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"无效的材料类型，可选：{valid_categories}")

    ext = _os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ext}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制：{MAX_FILE_SIZE // 1024 // 1024}MB")

    rel = _get_customer_dir(customer)
    stored_path = save_file(rel, category, file.filename, content)

    max_version = db.query(Material).filter(
        Material.application_id == application_id,
        Material.category == category,
    ).order_by(Material.version.desc()).first()
    new_version = (max_version.version if max_version else 0) + 1

    material = Material(
        application_id=application_id,
        category=category,
        filename=file.filename,
        file_path=stored_path,
        file_size=len(content),
        uploader_id=user.get("user_id") or user.get("id"),
        version=new_version,
    )
    db.add(material)
    db.flush()
    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="上传材料",
        resource_type="material",
        resource_id=material.id,
        new_value={"detail": f"材料: {file.filename}, 类型: {category}, 路径: {stored_path}"},
    )
    db.add(log)
    db.commit()
    db.refresh(material)
    return MaterialResponse.model_validate(material).model_dump()


@router.delete("/{material_id}")
async def delete_material(
    application_id: int, material_id: int, request: Request, db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    require_write_role(user)
    material = db.query(Material).filter(
        Material.id == material_id, Material.application_id == application_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    storage_delete(material.file_path)
    db.delete(material)
    db.commit()
    return {"message": "材料已删除"}


@router.put("/{material_id}")
async def update_material(
    application_id: int, material_id: int, request: Request,
    remark: str = Form(None), audit_status: str = Form(None),
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    material = db.query(Material).filter(
        Material.id == material_id, Material.application_id == application_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    if remark is not None:
        require_write_role(user)
        material.remark = remark
    if audit_status is not None:
        if audit_status not in [s.value for s in AuditStatus]:
            raise HTTPException(status_code=400, detail="无效的审核状态")
        material.audit_status = audit_status
    db.commit()
    db.refresh(material)
    return MaterialResponse.model_validate(material).model_dump()


@router.get("/file/{material_id}")
async def download_material_file(material_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    content = read_file(material.file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    # RFC 5987: UTF-8 encoded filename for non-ASCII support
    filename_encoded = quote(material.filename.encode('utf-8'), safe='')
    # ASCII fallback for legacy clients
    ascii_name = material.filename.encode('ascii', 'replace').decode('ascii').replace('?', '_')
    return Response(content=content, media_type="application/octet-stream",
                    headers={
                        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{filename_encoded}"
                    })


@router.get("/browse")
async def browse_files(application_id: int, request: Request, db: Session = Depends(get_db)):
    """返回客户目录的完整文件树"""
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    rel = _get_customer_dir(customer)
    return {"customer_dir": rel, "tree": storage_list(rel)}
