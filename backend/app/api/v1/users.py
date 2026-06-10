"""用户管理（admin）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import hash_password, require_admin
from app.models import AppUser
from app.schemas.auth import UserCreateIn, UserOut, UserUpdateIn
from app.services.template_service import get_or_404

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: AppUser = Depends(require_admin)):
    return db.execute(select(AppUser).order_by(AppUser.id)).scalars().all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreateIn, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    user = AppUser(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
        can_set_price=body.can_set_price,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"用户名已存在：{body.username}")
    write_audit(db, actor_id=admin.id, action="create", entity_type="app_user",
                entity_id=user.id, after={"username": body.username, "role": body.role})
    db.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdateIn,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    user = get_or_404(db, AppUser, user_id)
    data = body.model_dump(exclude_unset=True)
    before = {}
    if "password" in data:
        password = data.pop("password")
        if password:
            user.password_hash = hash_password(password)
            before["password"] = "<changed>"
    for field, value in data.items():
        if value is None:
            continue
        before[field] = getattr(user, field)
        setattr(user, field, value)
    write_audit(db, actor_id=admin.id, action="update", entity_type="app_user",
                entity_id=user.id, before=before,
                after={k: v for k, v in data.items() if v is not None})
    db.commit()
    return user
