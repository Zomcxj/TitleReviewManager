from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from models import Application, Customer, Material, OperationLog, User
from schemas import ApplicationUpdate, ApplicationResponse
from enums import VALID_TRANSITIONS, required_materials_for
from auth import get_current_user
from datetime import datetime
from typing import Optional
import uuid
from routers.notifications import create_notification

router = APIRouter(prefix="/api/applications", tags=["申报管理"])


class ApplicationCycleUpdate(BaseModel):
    """申报周期设置（字段均可选，只更新传入项）"""
    cycle_year: Optional[int] = None
    cycle_deadline: Optional[datetime] = None


def build_material_checklist(db: Session, app: Application) -> dict:
    """按专业类别统计必传材料完备性。

    材料完备性校验接口与"提交评审机构"共用本函数，保证两处判定口径一致。
    """
    required_categories = required_materials_for(app.professional_category or "")
    rows = (
        db.query(Material.category, func.count(Material.id))
        .filter(Material.application_id == app.id)
        .group_by(Material.category)
        .all()
    )
    counts = {category: count for category, count in rows}

    required = [
        {
            "category": category,
            "provided": counts.get(category, 0) > 0,
            "count": counts.get(category, 0),
        }
        for category in required_categories
    ]
    missing = [item["category"] for item in required if not item["provided"]]
    return {
        "professional_category": app.professional_category,
        "required": required,
        "missing": missing,
        "is_complete": len(missing) == 0,
        "total_required": len(required_categories),
        "total_provided": sum(1 for item in required if item["provided"]),
    }


@router.get("/{application_id}/material-checklist")
async def get_material_checklist(
    application_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """材料清单完备性校验（登录用户可访问）。"""
    await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    return build_material_checklist(db, app)


@router.get("/{application_id}")
async def get_application(application_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    return ApplicationResponse.model_validate(app).model_dump()


@router.put("/{application_id}")
async def update_application(
    application_id: int,
    data: ApplicationUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")

    old_status = app.status
    update_data = data.model_dump(exclude_unset=True)

    # 分配审核员：仅管理员/审核员可设置，且目标用户必须是审核员角色
    if "assigned_reviewer_id" in update_data:
        if user.get("role") not in ("admin", "reviewer"):
            raise HTTPException(status_code=403, detail="仅审核员或管理员可以分配审核员")
        reviewer_id = update_data["assigned_reviewer_id"]
        if reviewer_id is not None:
            reviewer = db.query(User).filter(User.id == reviewer_id).first()
            if not reviewer or reviewer.role != "reviewer":
                raise HTTPException(status_code=400, detail="指定的审核员不存在或不是审核员角色")

    if "status" in update_data:
        new_status = update_data["status"]
        if new_status not in VALID_TRANSITIONS.get(old_status, []):
            raise HTTPException(
                status_code=400,
                detail=f"不允许从 '{old_status}' 转换到 '{new_status}'"
            )
        # 角色规则：审核结果（返修/通过/不通过）仅审核员/管理员；其余状态流转仅业务员/管理员
        role = user.get("role")
        if old_status == "提交评审机构审核":
            if role not in ("reviewer", "admin"):
                raise HTTPException(status_code=403, detail="该状态变更需要审核员操作")
        elif role not in ("salesman", "admin"):
            raise HTTPException(status_code=403, detail="该状态变更需要业务员操作")
        if new_status == "提交评审机构审核":
            app.submitted_at = datetime.utcnow()
        app.status = new_status
        
        customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
        if customer:
            salesman_id = customer.assigned_salesman_id
            if salesman_id:
                if new_status == "资料补充":
                    create_notification(
                        db=db,
                        user_id=salesman_id,
                        title="需要补充资料",
                        content=f"客户 {customer.name} 的申报需要补充资料",
                        type="status_change",
                        related_type="application",
                        related_id=app.id,
                    )
                elif new_status == "返修":
                    create_notification(
                        db=db,
                        user_id=salesman_id,
                        title="需要返修",
                        content=f"客户 {customer.name} 的申报被退回，需要按意见返修",
                        type="status_change",
                        related_type="application",
                        related_id=app.id,
                    )
                elif new_status == "完成资料":
                    reviewers = db.query(User).filter(User.role == 'reviewer').all()
                    admins = db.query(User).filter(User.role == 'admin').all()
                    for u in reviewers + admins:
                        create_notification(
                            db=db,
                            user_id=u.id,
                            title="新申报待审核",
                            content=f"客户 {customer.name} 已提交审核，请前往审核工作台处理",
                            type="status_change",
                            related_type="application",
                            related_id=app.id,
                        )
                elif new_status in ["通过", "不通过"]:
                    create_notification(
                        db=db,
                        user_id=salesman_id,
                        title=f"审核结果：{new_status}",
                        content=f"客户 {customer.name} 的申报审核结果为：{new_status}",
                        type="status_change",
                        related_type="application",
                        related_id=app.id,
                    )
        
        log = OperationLog(
            user_id=user.get("user_id") or user.get("id"),
            username=user.get("username", ""),
            action=f"状态变更：{old_status} -> {new_status}",
            resource_type="application",
            resource_id=app.id,
            new_value={"detail": f"操作人：{user.get('username')}"},
        )
        db.add(log)

    for key, value in update_data.items():
        if key != "status":
            setattr(app, key, value)

    db.commit()
    db.refresh(app)
    return ApplicationResponse.model_validate(app).model_dump()


@router.put("/{application_id}/cycle")
async def set_application_cycle(
    application_id: int,
    data: ApplicationCycleUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """设置申报周期（年度 / 截止时间），仅业务员与管理员可操作。"""
    user = await get_current_user(request)
    if user.get("role") not in ("salesman", "admin"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可设置申报周期")

    app = (
        db.query(Application)
        .filter(Application.id == application_id, Application.is_deleted == False)  # noqa: E712
        .first()
    )
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")

    if user.get("role") == "salesman":
        customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
        if not customer or customer.assigned_salesman_id != (user.get("user_id") or user.get("id")):
            raise HTTPException(status_code=403, detail="仅可设置自己名下客户的申报周期")

    update_data = data.model_dump(exclude_unset=True)
    if "cycle_year" in update_data and update_data["cycle_year"] is not None:
        year = update_data["cycle_year"]
        if not isinstance(year, int) or isinstance(year, bool) or not (2000 <= year <= 2100):
            raise HTTPException(status_code=400, detail="申报年度不合法")

    old_value = {
        "cycle_year": app.cycle_year,
        "cycle_deadline": app.cycle_deadline.isoformat() if app.cycle_deadline else None,
    }
    for key, value in update_data.items():
        setattr(app, key, value)

    db.add(OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="设置申报周期",
        resource_type="application",
        resource_id=app.id,
        old_value=old_value,
        new_value={
            "cycle_year": app.cycle_year,
            "cycle_deadline": app.cycle_deadline.isoformat() if app.cycle_deadline else None,
        },
    ))
    db.commit()
    db.refresh(app)
    return ApplicationResponse.model_validate(app).model_dump()


@router.post("/{application_id}/submit-to-institution")
async def submit_to_institution(
    application_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    if user.get("role") not in ("salesman", "admin"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可提交评审机构")
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    if app.status != "完成资料":
        raise HTTPException(status_code=400, detail="只有完成资料状态才能提交评审机构")
    if user.get("role") == "salesman":
        customer = db.query(Customer).filter(Customer.id == app.customer_id).first()
        if not customer or customer.assigned_salesman_id != user.get("id"):
            raise HTTPException(status_code=403, detail="仅可提交自己名下客户的申报批次")
    # 材料完备性校验：状态/归属校验通过后再判定，缺料直接拒绝提交
    checklist = build_material_checklist(db, app)
    if checklist["missing"]:
        raise HTTPException(
            status_code=400,
            detail=f"缺少必传材料：{'、'.join(checklist['missing'])}，请补齐后再提交评审机构",
        )
    # body 解析容错：空 body 或非法 JSON 时使用空机构名，不抛 500
    institution_name = ""
    try:
        body = await request.json()
        if isinstance(body, dict):
            institution_name = body.get("institution_name", "") or ""
    except Exception:
        institution_name = ""
    old_status = app.status
    app.status = "提交评审机构审核"
    app.institution_name = institution_name
    app.submitted_at = datetime.utcnow()
    # 申报年度兜底：未设置时落到当前年份
    if not app.cycle_year:
        app.cycle_year = datetime.utcnow().year
    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action=f"状态变更: {old_status} -> 提交评审机构审核",
        resource_type="application",
        resource_id=app.id,
        new_value={"detail": f"报送机构: {institution_name}"},
    )
    db.add(log)
    db.commit()
    db.refresh(app)
    return ApplicationResponse.model_validate(app).model_dump()


@router.post("/{application_id}/reapply")
async def create_reapplication(
    application_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    if user.get("role") not in ("salesman", "admin"):
        raise HTTPException(status_code=403, detail="仅业务员和管理员可发起二次申报")
    old_app = db.query(Application).filter(Application.id == application_id).first()
    if not old_app:
        raise HTTPException(status_code=404, detail="申报批次不存在")
    if old_app.status != "不通过":
        raise HTTPException(status_code=400, detail="只有不通过的批次才能发起二次申报")
    if user.get("role") == "salesman":
        customer = db.query(Customer).filter(Customer.id == old_app.customer_id).first()
        if not customer or customer.assigned_salesman_id != user.get("id"):
            raise HTTPException(status_code=403, detail="仅可对自己名下客户的批次发起二次申报")
    # 重复申报检测：同客户 + 同专业 + 同级别 已有进行中的批次时拦截，避免重复建档
    duplicate = db.query(Application).filter(
        Application.customer_id == old_app.customer_id,
        Application.professional_category == old_app.professional_category,
        Application.title_level == old_app.title_level,
        Application.is_deleted == False,
        Application.status.notin_(["不通过", "通过"]),
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail=f"该客户已存在进行中的同专业同级别批次（{duplicate.batch_number}，当前状态：{duplicate.status}），请勿重复申报",
        )
    new_app = Application(
        customer_id=old_app.customer_id,
        professional_category=old_app.professional_category,
        title_level=old_app.title_level,
        status="二次申报",
        batch_number=f"BATCH-{uuid.uuid4().hex[:8].upper()}-R2",
    )
    db.add(new_app)
    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action="发起二次申报",
        resource_type="application",
        resource_id=new_app.id,
        new_value={"detail": f"基于原批次 {old_app.batch_number}"},
    )
    db.add(log)
    db.commit()
    db.refresh(new_app)
    return ApplicationResponse.model_validate(new_app).model_dump()


class StatusRevertRequest(BaseModel):
    """状态回退（纠错）请求"""
    target_status: str
    reason: str = ""


@router.post("/{application_id}/revert-status")
async def revert_application_status(
    application_id: int,
    data: StatusRevertRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """状态回退（纠错）—— 仅管理员。

    用于修正误操作（如误提交评审机构、误标通过）。允许回退到状态机中
    可以到达当前状态的前置状态，且必须填写原因以便审计追溯。
    """
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可回退状态")

    app = db.query(Application).filter(
        Application.id == application_id, Application.is_deleted == False
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="申报批次不存在")

    if not data.reason or not data.reason.strip():
        raise HTTPException(status_code=400, detail="请填写回退原因")

    old_status = app.status
    target = data.target_status

    if target == old_status:
        raise HTTPException(status_code=400, detail="目标状态与当前状态相同")

    # 允许回退到任意「能正向到达当前状态」的前置状态（含当前状态自身的前驱链）
    allowed_prev = [s.value for s, nxt in VALID_TRANSITIONS.items() if old_status in [n.value for n in nxt]]
    if target not in allowed_prev:
        raise HTTPException(
            status_code=400,
            detail=f"不允许从 '{old_status}' 回退到 '{target}'，可回退目标：{allowed_prev or '无'}",
        )

    app.status = target
    # 回退到提交前状态时，清空机构相关字段避免残留脏数据
    if target in ("完成资料", "资料补充", "初次申报", "二次申报"):
        app.submitted_at = None
        app.institution_name = None

    log = OperationLog(
        user_id=user.get("user_id") or user.get("id"),
        username=user.get("username", ""),
        action=f"状态回退（纠错）：{old_status} -> {target}",
        resource_type="application",
        resource_id=app.id,
        old_value={"status": old_status},
        new_value={"status": target, "detail": f"原因：{data.reason.strip()}"},
    )
    db.add(log)
    db.commit()
    db.refresh(app)
    return ApplicationResponse.model_validate(app).model_dump()
