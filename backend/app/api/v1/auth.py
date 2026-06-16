import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import (
    decode_token,
    get_current_user,
    make_access_token,
    make_refresh_token,
    verify_password,
)
from app.models import AppUser
from app.schemas.auth import LoginIn, RefreshIn, TokenPair, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# 登录失败限频(进程内·尽力而为)：同一用户名滑动窗口内失败过多即临时 429，抬高暴力破解成本。
# 注：进程内状态、多 worker 不共享，是缓解而非根治；生产级需 Redis/DB 共享计数或前置限流网关。
_LOGIN_FAILS: dict[str, list[float]] = {}
_FAIL_WINDOW = 300.0  # 5 分钟滑动窗口
_FAIL_MAX = 10        # 窗口内最多 10 次失败，超过即拒绝一段时间


def _too_many_fails(username: str) -> bool:
    now = time.monotonic()
    fails = [t for t in _LOGIN_FAILS.get(username, []) if now - t < _FAIL_WINDOW]
    _LOGIN_FAILS[username] = fails
    return len(fails) >= _FAIL_MAX


@router.post("/login", response_model=TokenPair)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    if _too_many_fails(body.username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "登录尝试过于频繁，请稍后再试")
    user = db.execute(
        select(AppUser).where(AppUser.username == body.username)
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        _LOGIN_FAILS.setdefault(body.username, []).append(time.monotonic())  # 记一次失败
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    _LOGIN_FAILS.pop(body.username, None)  # 登录成功即清零该用户失败计数
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    write_audit(
        db, actor_id=user.id, action="login", entity_type="app_user", entity_id=user.id,
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return TokenPair(
        access_token=make_access_token(user.id), refresh_token=make_refresh_token(user.id)
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenPair:
    user_id = decode_token(body.refresh_token, "refresh")
    user = db.get(AppUser, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return TokenPair(
        access_token=make_access_token(user.id), refresh_token=make_refresh_token(user.id)
    )


@router.get("/me", response_model=UserOut)
def me(user: AppUser = Depends(get_current_user)) -> AppUser:
    return user
