"""配置草稿：半成品选配，仅 owner 可见可改。非 SKU、不参与指纹与报价。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models import AppUser, ConfigDraft, NodeType
from app.services.template_service import get_or_404

router = APIRouter(prefix="/config-drafts", tags=["drafts"])


class DraftIn(BaseModel):
    root_type_id: int
    title: str | None = Field(default=None, max_length=200)
    payload: dict


class DraftOut(BaseModel):
    id: int
    root_type_id: int
    root_type_name: str = ""
    title: str | None
    payload: dict
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


def _out(db: Session, d: ConfigDraft) -> DraftOut:
    out = DraftOut.model_validate(d)
    nt = db.get(NodeType, d.root_type_id)
    out.root_type_name = nt.name if nt else ""
    return out


def _own_or_404(db: Session, draft_id: int, user: AppUser) -> ConfigDraft:
    draft = db.get(ConfigDraft, draft_id)
    if draft is None or draft.owner_id != user.id:
        raise HTTPException(404, "草稿不存在")
    return draft


@router.get("", response_model=list[DraftOut])
def list_my_drafts(
    db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)
):
    rows = db.execute(
        select(ConfigDraft)
        .where(ConfigDraft.owner_id == user.id)
        .order_by(ConfigDraft.updated_at.desc())
        .limit(50)
    ).scalars().all()
    return [_out(db, d) for d in rows]


@router.post("", response_model=DraftOut, status_code=201)
def create_draft(
    body: DraftIn, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)
):
    get_or_404(db, NodeType, body.root_type_id)
    draft = ConfigDraft(owner_id=user.id, **body.model_dump())
    db.add(draft)
    db.commit()
    return _out(db, draft)


@router.put("/{draft_id}", response_model=DraftOut)
def update_draft(
    draft_id: int, body: DraftIn,
    db: Session = Depends(get_db), user: AppUser = Depends(get_current_user),
):
    draft = _own_or_404(db, draft_id, user)
    draft.root_type_id = body.root_type_id
    draft.title = body.title
    draft.payload = body.payload
    db.commit()
    return _out(db, draft)


@router.delete("/{draft_id}", status_code=204)
def delete_draft(
    draft_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)
):
    draft = _own_or_404(db, draft_id, user)
    db.delete(draft)
    db.commit()
