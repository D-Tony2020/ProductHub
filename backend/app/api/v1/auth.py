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


@router.post("/login", response_model=TokenPair)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    user = db.execute(
        select(AppUser).where(AppUser.username == body.username)
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
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
