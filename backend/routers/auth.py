from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import AuthStatus, LoginResponse, PasswordChangeIn, SystemLogin
from system_auth import authenticate_user, create_token, parse_token, require_system_auth, user_must_change_password
from user_service import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_status(principal, must_change_password: bool = False) -> AuthStatus:
    return AuthStatus(
        authenticated=True,
        username=principal.username,
        role=principal.role,
        department=principal.department,
        display_name=principal.display_name,
        must_change_password=must_change_password,
    )


@router.get("/status", response_model=AuthStatus)
def auth_status(x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token")):
    principal = parse_token(x_auth_token or "")
    if not principal:
        return AuthStatus(authenticated=False)
    return _auth_status(principal, user_must_change_password(principal.user_id))


@router.post("/login", response_model=LoginResponse)
def login(payload: SystemLogin, db: Session = Depends(get_db)):
    principal, must_change = authenticate_user(db, payload.username, payload.password)
    if not principal:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    message = "登录成功，请先修改初始密码" if must_change else "登录成功"
    return LoginResponse(
        token=create_token(principal),
        message=message,
        username=principal.username,
        role=principal.role,
        department=principal.department,
        display_name=principal.display_name,
        must_change_password=must_change,
    )


@router.get("/me", response_model=AuthStatus)
def me(principal=Depends(require_system_auth)):
    return _auth_status(principal, user_must_change_password(principal.user_id))


@router.post("/change-password", response_model=LoginResponse)
def change_password(
    body: PasswordChangeIn,
    db: Session = Depends(get_db),
    principal=Depends(require_system_auth),
):
    if principal.user_id == 0:
        raise HTTPException(status_code=400, detail="配置管理员账号请在系统配置中修改密码")
    row = db.query(User).filter(User.id == principal.user_id, User.is_active.is_(True)).first()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not verify_password(body.old_password, row.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    row.password_hash = hash_password(body.new_password)
    row.must_change_password = False
    db.commit()
    principal.display_name = row.display_name or row.username
    return LoginResponse(
        token=create_token(principal),
        message="密码已修改",
        username=principal.username,
        role=principal.role,
        department=principal.department,
        display_name=principal.display_name,
        must_change_password=False,
    )
