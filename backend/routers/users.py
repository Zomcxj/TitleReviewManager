from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User, Customer
from schemas import UserResponse, UserCreate, UserUpdate, PasswordChange
from auth import (
    get_current_user, hash_password, verify_password,
    create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES,
)
from typing import List
from datetime import datetime

router = APIRouter(prefix="/api/users", tags=["用户管理"])


def admin_only(user: dict):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")


@router.get("/", response_model=List[UserResponse])
async def list_users(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    admin_only(user)
    users = db.query(User).order_by(User.id).all()
    return [UserResponse.model_validate(u).model_dump(mode="json") for u in users]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    admin_only(user)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    return u


@router.post("/", response_model=UserResponse)
async def create_user(data: UserCreate, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    admin_only(user)
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    valid_roles = ["admin", "salesman", "reviewer"]
    if data.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"无效角色，可选：{valid_roles}")
    u = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role=data.role,
        real_name=data.real_name,
        email=data.email,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, data: UserUpdate, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    admin_only(user)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    upd = data.model_dump(exclude_unset=True)
    if "password" in upd:
        # 明文密码 pop 出来单独 hash，避免 setattr 循环把明文写入 User.password
        upd["password_hash"] = hash_password(upd.pop("password"))
    if "username" in upd and upd["username"] != u.username:
        if db.query(User).filter(User.username == upd["username"]).first():
            raise HTTPException(status_code=400, detail="用户名已存在")
    for k, v in upd.items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return u


@router.delete("/{user_id}")
async def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    admin_only(user)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == user.get("id"):
        raise HTTPException(status_code=400, detail="不能删除自己")
    # 名下仍有客户的业务员不允许删除，需先转让客户
    if db.query(Customer).filter(Customer.assigned_salesman_id == user_id).first():
        raise HTTPException(status_code=400, detail="该业务员名下还有客户，请先转让")
    db.delete(u)
    db.commit()
    return {"message": "用户已删除"}


@router.post("/change-password")
async def change_password(data: PasswordChange, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    uid = user.get("user_id") or user.get("id")
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not verify_password(data.old_password, u.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if data.old_password == data.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    u.password_hash = hash_password(data.new_password)
    # 改密成功后解除强制改密标记，并记录改密时间（供密码有效期策略使用）
    u.must_change_password = False
    u.password_changed_at = datetime.utcnow()
    # 自增 token 版本：其他设备上的旧 token 立即失效（改密后必须重新登录）
    u.token_version = (u.token_version or 0) + 1
    db.commit()
    new_token = create_access_token({
        "user_id": u.id, "id": u.id, "username": u.username,
        "role": u.role, "tv": u.token_version,
    })
    resp = JSONResponse(content={"message": "密码已修改，请使用新密码重新登录"})
    # 当前会话换发新 token，避免用户改密后立刻被踢出
    resp.set_cookie(
        key="access_token", value=new_token,
        httponly=True, samesite="lax", max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return resp


@router.post("/{user_id}/reset-password")
async def reset_user_password(user_id: int, data: dict, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request)
    admin_only(user)
    # 验证管理员密码
    admin = db.query(User).filter(User.id == user.get("user_id")).first()
    if not admin:
        raise HTTPException(status_code=404, detail="管理员不存在")
    admin_password = data.get("admin_password", "")
    if not verify_password(admin_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="管理员密码错误")
    # 修改目标用户密码
    new_password = data.get("new_password", "")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    target.password_hash = hash_password(new_password)
    # 管理员重置的密码属于临时口令，要求该用户下次登录后自行修改
    target.must_change_password = True
    target.password_changed_at = datetime.utcnow()
    # 使目标用户已登录的会话立即失效
    target.token_version = (target.token_version or 0) + 1
    db.commit()
    return {"message": "密码已修改，该用户下次登录需自行修改密码"}
