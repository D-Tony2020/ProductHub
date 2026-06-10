"""认证与授权：JWT（access/refresh）+ bcrypt 口令哈希 + 角色依赖。"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import AppUser

_bearer = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def _make_token(user_id: int, token_type: str, lifetime: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def make_access_token(user_id: int) -> str:
    return _make_token(user_id, "access", timedelta(minutes=get_settings().access_token_minutes))


def make_refresh_token(user_id: int) -> str:
    return _make_token(user_id, "refresh", timedelta(days=get_settings().refresh_token_days))


def decode_token(token: str, expected_type: str) -> int:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证无效或已过期")
    if payload.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证类型错误")
    return int(payload["sub"])


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    user_id = decode_token(credentials.credentials, "access")
    user = db.get(AppUser, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return user


def require_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def require_price_setter(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role != "admin" and not user.can_set_price:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要录价权限")
    return user
