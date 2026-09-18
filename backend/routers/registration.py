from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models import RegistrationToken, Customer, Application, OperationLog, User
from schemas import RegistrationTokenCreate, RegistrationTokenResponse, SelfRegisterRequest, CustomerResponse
from enums import CustomerSource
from auth import get_current_user
from datetime import datetime, timedelta, timezone
import secrets
import uuid
import os
import socket
from typing import List, Dict

def get_local_ip() -> str:
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# 优先使用环境变量，否则自动检测局域网 IP
_env_url = os.getenv("PUBLIC_URL")
if _env_url:
    PUBLIC_URL = _env_url.rstrip("/")
else:
    PUBLIC_URL = f"http://{get_local_ip()}:8000"

router = APIRouter(prefix="/api/registration-links", tags=["专属注册链接"])


@router.get("/", response_model=List[Dict])
async def list_tokens(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    if user["role"] not in ("salesman", "admin"):
        raise HTTPException(status_code=403, detail="只有业务员和管理员可以查看注册链接")

    # Admin sees all tokens, salesman sees only their own
    if user["role"] == "admin":
        query = db.query(RegistrationToken)
    else:
        query = db.query(RegistrationToken).filter(RegistrationToken.salesman_id == user["user_id"])
    
    tokens = query.order_by(RegistrationToken.created_at.desc()).all()
    result = []
    for t in tokens:
        salesman = db.query(User).filter(User.id == t.salesman_id).first()
        result.append({
            **RegistrationTokenResponse.model_validate(t).model_dump(),
            "salesman_name": salesman.real_name if salesman else "",
            "link": f"/apply?token={t.token}",
            "full_link": f"{PUBLIC_URL}/apply?token={t.token}",
        })
    return result


@router.post("/", response_model=RegistrationTokenResponse)
async def create_token(
    data: RegistrationTokenCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = await get_current_user(request)
    if user["role"] not in ("salesman", "admin"):
        raise HTTPException(status_code=403, detail="只有业务员和管理员可以创建注册链接")

    token_value = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_days or 7)

    token = RegistrationToken(
        token=token_value,
        salesman_id=user["user_id"],
        expires_at=expires_at,
        max_uses=data.max_uses or 0,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return RegistrationTokenResponse.model_validate(token)


@router.delete("/{token_id}")
async def deactivate_token(token_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    token = db.query(RegistrationToken).filter(RegistrationToken.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="链接不存在")
    if user["role"] != "admin" and token.salesman_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="无权操作此链接")
    token.is_active = False
    db.commit()
    return {"message": "链接已停用"}


@router.delete("/{token_id}/hard")
async def hard_delete_token(token_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以彻底删除链接")
    token = db.query(RegistrationToken).filter(RegistrationToken.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="链接不存在")
    db.delete(token)
    db.commit()
    return {"message": "链接已彻底删除"}


@router.get("/validate/{token_value}")
async def validate_token(token_value: str, db: Session = Depends(get_db)):
    token = db.query(RegistrationToken).filter(
        RegistrationToken.token == token_value,
        RegistrationToken.is_active == True,
    ).first()
    if not token:
        raise HTTPException(status_code=404, detail="链接无效或已停用")
    now = datetime.now(timezone.utc)
    expires = token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=410, detail="链接已过期")
    if token.max_uses > 0 and token.use_count >= token.max_uses:
        raise HTTPException(status_code=410, detail="链接使用次数已达上限")

    salesman = db.query(User).filter(User.id == token.salesman_id).first()
    return {
        "valid": True,
        "salesman_name": salesman.real_name if salesman else "",
        "expires_at": token.expires_at.isoformat(),
        "remaining_uses": token.max_uses - token.use_count if token.max_uses > 0 else "无限",
    }


@router.post("/self-register", response_model=CustomerResponse)
async def self_register(
    data: SelfRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    token = db.query(RegistrationToken).filter(
        RegistrationToken.token == data.token,
        RegistrationToken.is_active == True,
    ).with_for_update().first()
    if not token:
        raise HTTPException(status_code=400, detail="注册链接无效")
    now = datetime.now(timezone.utc)
    expires = token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=400, detail="注册链接已过期")
    if token.max_uses > 0 and token.use_count >= token.max_uses:
        raise HTTPException(status_code=400, detail="注册链接使用次数已达上限")

    existing = db.query(Customer).filter(
        Customer.id_number == data.id_number, Customer.is_deleted == False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该身份证号已存在")

    customer = Customer(
        name=data.name,
        id_number=data.id_number,
        phone=data.phone,
        education=data.education,
        current_title=data.current_title,
        current_title_year=data.current_title_year,
        work_unit=data.work_unit,
        position=data.position,
        professional_years=data.professional_years,
        project_experiences=data.project_experiences,
        assigned_salesman_id=token.salesman_id,
        source=data.source or CustomerSource.SELF.value,
    )
    db.add(customer)
    db.flush()

    app = Application(
        customer_id=customer.id,
        batch_number=f"BATCH-{uuid.uuid4().hex[:8].upper()}",
    )
    db.add(app)
    db.flush()

    token.use_count += 1

    log = OperationLog(
        user_id=token.salesman_id,
        username="",
        action="客户自助提交",
        resource_type="customer",
        resource_id=customer.id,
        new_value={"detail": "客户通过专属链接提交基本信息"},
    )
    db.add(log)
    db.commit()
    db.refresh(customer)
    return CustomerResponse.model_validate(customer)
