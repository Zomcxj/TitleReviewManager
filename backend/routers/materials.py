import logging
import os as _os
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from auth import get_current_user
from database import get_db
from enums import ALLOWED_FILE_EXTENSIONS, MAX_FILE_SIZE, AuditStatus, MaterialCategory
from models import Application, Customer, Material, OperationLog
from schemas import MaterialResponse
from storage import customer_dir, full_path, get_pinyin_initial, open_file, save_file_from_fileobj
from storage import delete_file as storage_delete
from storage import list_files as storage_list
from utils.system_config import get_config
from utils.timeutil import utcnow

router = APIRouter(prefix="/api/applications/{application_id}/materials", tags=["材料管理"])
logger = logging.getLogger(__name__)

WRITE_ROLES = {"admin", "salesman"}


def require_write_role(user: dict):
    if user.get("role") not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="仅业务员和管理员可操作")


def check_customer_ownership(user: dict, customer: Customer):
    """Data isolation: salesmen can only operate on materials of their own customers; admin/reviewer are unrestricted."""
    if user.get("role") == "salesman" and (
        not customer or customer.assigned_salesman_id != (user.get("id") or user.get("user_id"))
    ):
        raise HTTPException(status_code=403, detail="无权操作该客户的材料")


def _max_file_size(db: Session) -> tuple[int, int]:
    """Per-file size limit, returns (bytes, MB). Driven by the system config max_file_size_mb, with enums.MAX_FILE_SIZE as fallback."""
    try:
        mb = int(get_config(db, "max_file_size_mb"))
    except (TypeError, ValueError):
        mb = MAX_FILE_SIZE // 1024 // 1024
    return mb * 1024 * 1024, mb


def _get_customer_dir(customer: Customer) -> str:
    year = customer.created_at.year if customer.created_at else utcnow().year
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
        # Strip LIKE wildcard special characters to prevent wildcard injection
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
    # Size check BEFORE reading any content (declared size is set by Starlette from
    # the multipart header, so an oversized upload is rejected without buffering it)
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制：{max_mb}MB")

    # Content validation: prevent files of other formats being disguised as pdf/images by extension renaming
    from utils.upload_guard import validate_file_content
    head = await file.read(64)
    if not head and (file.size or 0) > 0:
        raise HTTPException(status_code=400, detail="文件内容为空")
    content_err = validate_file_content(file.filename, head)
    if content_err:
        raise HTTPException(status_code=400, detail=content_err)
    await file.seek(0)  # rewind so save_file_from_fileobj streams from the very start

    rel = _get_customer_dir(customer)
    # Use the sanitized filename for both disk storage and DB records, avoiding raw names like ../ being written to the database
    from utils.upload_guard import safe_filename
    clean_name = safe_filename(file.filename)
    # Chunked write: peak memory is one 1MB chunk instead of the whole file
    try:
        stored_path, file_bytes = save_file_from_fileobj(rel, category, clean_name, file.file, max_bytes=max_bytes)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制：{max_mb}MB") from None

    # Row-level lock on the version number, so concurrent uploads of the same category
    # cannot pick the same version (SQLite ignores FOR UPDATE but write transactions are
    # serial anyway; under PostgreSQL it genuinely blocks concurrent transactions)
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
        file_size=file_bytes,
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
        # Physical file deletion failure only warns; it does not block the DB record deletion
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
    # Stream from disk via FileResponse: a single download used to materialise the
    # whole file (up to the 50MB cap) in memory as one bytes object
    abs_path = full_path(material.file_path)
    if abs_path is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    # PII compliance: leave an audit trail for material downloads (recorded only after a successful download)
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
    return FileResponse(abs_path, media_type="application/octet-stream",
                    headers={
                        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{filename_encoded}"
                    })


@router.get("/browse")
async def browse_files(application_id: int, request: Request, db: Session = Depends(get_db)):
    """Return the full file tree of the customer directory."""
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


@router.get("/download-zip")
async def download_materials_zip(
    application_id: int,
    request: Request,
    category: str = None,
    db: Session = Depends(get_db),
):
    """Batch-download an application's materials as a zip (optionally filtered by category).

    Business context: downloading files one by one is highly inconvenient when
    the customer or agency needs a complete set of materials.
    Implementation note: materials are stored on the NAS and each is read into
    memory before packing; the total size per request is capped to avoid
    consuming too much memory at once (users are prompted to download in
    batches when exceeded).
    """
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
    check_customer_ownership(user, customer)

    q = db.query(Material).filter(Material.application_id == application_id)
    if category:
        q = q.filter(Material.category == category)
    materials = q.order_by(Material.category, Material.version).all()
    if not materials:
        raise HTTPException(status_code=404, detail="该批次没有可下载的材料")

    import os
    import shutil
    import tempfile
    import zipfile

    MAX_TOTAL_BYTES = 300 * 1024 * 1024  # 300MB cap per packing request

    total = 0
    added = 0
    missing = []
    # Keep only the latest version of each category (older versions are excluded to avoid confusion)
    latest: dict = {}
    for m in materials:
        latest[(m.category, )] = m  # already sorted by version ascending, so the last one is the latest

    # Stream to a temp file instead of BytesIO: packing up to 300MB of materials
    # in memory once peaked at ~3 copies of the data (content + compressed buffer
    # + buf.read()); with several concurrent requests this is exactly the
    # "unexplained memory spike". Files are copied chunk-wise from disk, so peak
    # memory is one chunk no matter the total size.
    fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="materials_")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
            # ZIP_STORED on purpose: the whitelist is pdf/docx/jpg/png — already
            # compressed formats where DEFLATED burns CPU for ~0% size gain.
            for (cat, ), m in sorted(latest.items(), key=lambda x: x[0][0]):
                fobj = open_file(m.file_path)
                if fobj is None:
                    missing.append(m.filename)
                    continue
                with fobj:
                    try:
                        size = fobj.seek(0, 2)  # size without reading content into memory
                        fobj.seek(0)
                    except OSError:
                        missing.append(m.filename)
                        continue
                    total += size
                    if total > MAX_TOTAL_BYTES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"材料总大小超过 {MAX_TOTAL_BYTES // 1024 // 1024}MB，请按类别分批下载",
                        )
                    # Keep category directories inside the zip for easy sorting after extraction
                    arcname = f"{cat}/{m.filename}"
                    # Stream via zf.open(w): zipfile.write() only accepts a path, and
                    # writestr() would load the whole file — copyfileobj copies in
                    # fixed-size chunks so memory stays flat
                    with zf.open(arcname, "w") as dst:
                        shutil.copyfileobj(fobj, dst, 1024 * 1024)
                    added += 1

            if missing:
                zf.writestr("_缺失文件说明.txt",
                            "以下材料在存储中不存在，可能已被移动或删除：\n" + "\n".join(missing))
    except HTTPException:
        os.remove(tmp_path)
        raise
    except Exception:
        os.remove(tmp_path)
        raise

    if added == 0:
        os.remove(tmp_path)
        raise HTTPException(status_code=404, detail="材料文件均不存在于存储中")

    # Download audit (materials contain customer ID document images, must leave a trail)
    db.add(OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="批量下载材料",
        resource_type="application",
        resource_id=application_id,
        new_value={"detail": f"客户: {customer.name if customer else ''}, 打包 {added} 份, 类别: {category or '全部'}"},
    ))
    db.commit()

    from urllib.parse import quote
    zip_name = f"{customer.name if customer else '客户'}_材料_{app.batch_number or application_id}.zip"
    encoded = quote(zip_name, safe="")
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=\"materials.zip\"; filename*=UTF-8''{encoded}"},
        background=BackgroundTask(os.remove, tmp_path),  # temp file removed after the response is sent
    )
