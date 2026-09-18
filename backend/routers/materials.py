from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import get_db
from models import Material, Application, Customer, User, OperationLog
from schemas import MaterialResponse
from enums import MaterialCategory, AuditStatus
from auth import get_current_user
from enums import ALLOWED_FILE_EXTENSIONS, MAX_FILE_SIZE
from datetime import datetime
from utils.system_config import get_config
from storage import save_file, read_file, delete_file as storage_delete, list_files as storage_list, customer_dir, get_pinyin_initial
import logging
import os as _os
from urllib.parse import quote

router = APIRouter(prefix="/api/applications/{application_id}/materials", tags=["材料管理"])
logger = logging.getLogger(__name__)

WRITE_ROLES = {"admin", "salesman"}


def require_write_role(user: dict):
    if user.get("role") not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="仅业务员和管理员可操作")


def check_customer_ownership(user: dict, customer: Customer):
    """数据隔离：业务员只能操作自己名下客户的材料，admin/reviewer 不限。"""
    if user.get("role") == "salesman":
        if not customer or customer.assigned_salesman_id != (user.get("id") or user.get("user_id")):
            raise HTTPException(status_code=403, detail="无权操作该客户的材料")


def _max_file_size(db: Session) -> tuple[int, int]:
    """单文件大小上限，返回 (字节数, MB 数)。由系统配置 max_file_size_mb 驱动，enums.MAX_FILE_SIZE 作为兜底。"""
    try:
        mb = int(get_config(db, "max_file_size_mb"))
    except (TypeError, ValueError):
        mb = MAX_FILE_SIZE // 1024 // 1024
    return mb * 1024 * 1024, mb


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
    check_customer_ownership(user, customer)

    q = db.query(Material).filter(Material.application_id == application_id)
    if keyword:
        # 过滤 LIKE 通配符特殊字符，避免通配符注入
        keyword = keyword.replace("%", "").replace("_", "").replace("\\", "")
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


@router.post("")
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
    check_customer_ownership(user, customer)
    valid_categories = [c.value for c in MaterialCategory]
    if category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"无效的材料类型，可选：{valid_categories}")

    ext = _os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ext}")

    max_bytes, max_mb = _max_file_size(db)
    if file.size is not None:
        # 优先使用请求声明的文件大小，超限时不再读取内容
        if file.size > max_bytes:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制：{max_mb}MB")
        content = await file.read()
    else:
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制：{max_mb}MB")

    # 内容校验：防止把其他格式改扩展名伪装成 pdf/图片上传
    from utils.upload_guard import validate_file_content
    content_err = validate_file_content(file.filename, content)
    if content_err:
        raise HTTPException(status_code=400, detail=content_err)

    rel = _get_customer_dir(customer)
    # 落盘与入库统一使用净化后的文件名，避免把 ../ 之类的原始名写进数据库
    from utils.upload_guard import safe_filename
    clean_name = safe_filename(file.filename)
    stored_path = save_file(rel, category, clean_name, content)

    # 版本号加行级锁，避免并发上传同类别材料时取到相同版本号
    # （SQLite 忽略 FOR UPDATE 但写事务本身串行；PostgreSQL 下真正阻塞并发事务）
    max_version = (
        db.query(Material)
        .filter(Material.application_id == application_id, Material.category == category)
        .order_by(Material.version.desc())
        .with_for_update()
        .first()
    )
    new_version = (max_version.version if max_version else 0) + 1

    material = Material(
        application_id=application_id,
        category=category,
        filename=clean_name,
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
        new_value={"detail": f"材料: {clean_name}, 类型: {category}, 路径: {stored_path}"},
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
    app = db.query(Application).filter(Application.id == application_id).first()
    customer = db.query(Customer).filter(Customer.id == app.customer_id).first() if app else None
    check_customer_ownership(user, customer)

    try:
        storage_delete(material.file_path)
    except Exception:
        # 物理文件删除失败仅告警，不阻断数据库记录删除
        logger.warning("删除材料物理文件失败: %s", material.file_path, exc_info=True)

    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="删除材料",
        resource_type="material",
        resource_id=material.id,
        new_value={"detail": f"材料: {material.filename}, 类型: {material.category}"},
    )
    db.add(log)
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
    app = db.query(Application).filter(Application.id == application_id).first()
    customer = db.query(Customer).filter(Customer.id == app.customer_id).first() if app else None

    if remark is not None:
        require_write_role(user)
        check_customer_ownership(user, customer)
        material.remark = remark
    if audit_status is not None:
        if user.get("role") not in ("reviewer", "admin"):
            raise HTTPException(status_code=403, detail="仅审核员和管理员可变更审核状态")
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
    app = db.query(Application).filter(Application.id == material.application_id).first()
    customer = db.query(Customer).filter(Customer.id == app.customer_id).first() if app else None
    check_customer_ownership(user, customer)
    content = read_file(material.file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    # PII 合规：材料下载留痕（下载成功后才记录）
    detail = f"下载材料: {material.filename}, 客户: {customer.name if customer else ''}"
    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="下载材料",
        resource_type="material",
        resource_id=material.id,
        new_value={"detail": detail},
    )
    db.add(log)
    db.commit()
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
    check_customer_ownership(user, customer)
    rel = _get_customer_dir(customer)
    return {"customer_dir": rel, "tree": storage_list(rel)}
