from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Material, Application, User, OperationLog
from schemas import MaterialResponse, MaterialCategory, AuditStatus
from auth import get_current_user
from datetime import datetime
import os
import uuid
from pathlib import Path

router = APIRouter(prefix="/api/applications/{application_id}/materials", tags=["材料管理"])
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Allowed file extensions and MIME types
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.get("/")
async def list_materials(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    materials = db.query(Material).filter(Material.application_id == application_id).all()
    return [MaterialResponse.model_validate(m).model_dump() for m in materials]


@router.post("/")
async def upload_material(
    application_id: int,
    request: Request,
    category: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")

    valid_categories = [c.value for c in MaterialCategory]
    if category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"无效的材料类型，可选：{valid_categories}")

    # Validate file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{ext}，允许：{', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Validate file size
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制：{MAX_FILE_SIZE // 1024 // 1024}MB"
        )

    unique_name = f"{uuid.uuid4().hex}{ext}"
    app_dir = os.path.join(UPLOAD_DIR, str(application_id))
    os.makedirs(app_dir, exist_ok=True)
    file_path = os.path.join(app_dir, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    max_version = db.query(Material).filter(
        Material.application_id == application_id,
        Material.category == category,
    ).order_by(Material.version.desc()).first()
    new_version = (max_version.version if max_version else 0) + 1

    material = Material(
        application_id=application_id,
        category=category,
        filename=file.filename,
        file_path=f"uploads/{application_id}/{unique_name}",
        file_size=len(content),
        uploader_id=user["user_id"],
        version=new_version,
    )
    db.add(material)
    log = OperationLog(
        application_id=application_id,
        customer_id=app.customer_id,
        action="上传材料",
        detail=f"材料: {file.filename}, 类型: {category}, 版本: v{new_version}",
        actor_id=user["user_id"],
    )
    db.add(log)
    db.commit()
    db.refresh(material)
    return MaterialResponse.model_validate(material).model_dump()


@router.delete("/{material_id}")
async def delete_material(
    application_id: int,
    material_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.application_id == application_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), material.file_path)
    if os.path.exists(file_path):
        os.remove(file_path)
    db.delete(material)
    db.commit()
    return {"message": "材料已删除"}


@router.put("/{material_id}")
async def update_material(
    application_id: int,
    material_id: int,
    request: Request,
    remark: str = Form(None),
    audit_status: str = Form(None),
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.application_id == application_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    if remark is not None:
        material.remark = remark
    if audit_status is not None:
        valid_statuses = [s.value for s in AuditStatus]
        if audit_status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"无效的审核状态")
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
    
    # Path traversal protection: resolve to absolute path and verify it's within UPLOAD_DIR
    base_dir = os.path.dirname(os.path.dirname(__file__))
    requested_path = os.path.join(base_dir, material.file_path)
    resolved_path = os.path.realpath(requested_path)
    allowed_base = os.path.realpath(UPLOAD_DIR)
    
    if not resolved_path.startswith(allowed_base):
        raise HTTPException(status_code=403, detail="Invalid file path")
    
    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(resolved_path, filename=material.filename)
