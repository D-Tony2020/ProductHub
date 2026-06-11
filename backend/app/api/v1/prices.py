"""录价：append-only。改价 = 同事务关闭旧记录（valid_to=D-1）+ 插入新记录（valid_from=D）。

EXCLUDE 约束兜底并发与期重叠；本路由不提供任何 UPDATE price 入口。
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import get_current_user, require_price_setter
from app.models import AppUser, Sku, SkuPrice
from app.schemas.sku import PriceIn, PriceOut
from app.services.template_service import get_or_404

router = APIRouter(prefix="/skus/{sku_id}/prices", tags=["prices"])


def _price_out(db: Session, p: SkuPrice) -> PriceOut:
    creator = db.get(AppUser, p.created_by) if p.created_by else None
    return PriceOut(
        id=p.id,
        price=p.price,
        currency=p.currency,
        valid_from=p.valid_from.isoformat(),
        valid_to=p.valid_to.isoformat() if p.valid_to else None,
        note=p.note,
        created_by_name=creator.display_name if creator else None,
        created_at=p.created_at.isoformat() if p.created_at else None,
    )


@router.get("", response_model=list[PriceOut])
def history(
    sku_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    get_or_404(db, Sku, sku_id)
    rows = db.execute(
        select(SkuPrice)
        .where(SkuPrice.sku_id == sku_id)
        .order_by(SkuPrice.valid_from.desc(), SkuPrice.id.desc())
    ).scalars().all()
    return [_price_out(db, p) for p in rows]


@router.post("", response_model=PriceOut, status_code=201)
def set_price(
    sku_id: int,
    body: PriceIn,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_price_setter),
):
    sku = get_or_404(db, Sku, sku_id)
    if sku.status != "active":
        raise HTTPException(409, "已作废 SKU 不可录价，请先恢复")
    currency = body.currency or get_settings().default_currency
    valid_from = date.fromisoformat(body.valid_from) if body.valid_from else date.today()

    # 关闭当前开放价（valid_to 为空且生效中）：止于新价前一天
    open_price = db.execute(
        select(SkuPrice).where(
            SkuPrice.sku_id == sku_id,
            SkuPrice.currency == currency,
            SkuPrice.valid_to.is_(None),
        )
    ).scalar_one_or_none()
    before = None
    action = "set_price"
    if open_price is not None:
        before = {"price": str(open_price.price), "valid_from": open_price.valid_from.isoformat()}
        if open_price.valid_from == valid_from:
            # 同日纠错：手滑录错必须能当天改。日颗粒度下旧记录无法闭区间收尾
            # （valid_to < valid_from 违反约束），故对"只追加"做受控例外：
            # 删除当日错误记录，原值完整保留在审计 before_json 中。
            action = "correct_price"
            db.delete(open_price)
            db.flush()
        elif open_price.valid_from > valid_from:
            raise HTTPException(
                409,
                f"新价生效日 {valid_from} 早于现行价生效日 {open_price.valid_from}，"
                "不允许回溯覆盖历史价格",
            )
        else:
            open_price.valid_to = valid_from - timedelta(days=1)

    new_price = SkuPrice(
        sku_id=sku_id, price=body.price, currency=currency,
        valid_from=valid_from, valid_to=None, note=body.note, created_by=user.id,
    )
    db.add(new_price)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "价格生效期与既有记录重叠（数据库排他约束拒绝），请刷新后重试")
    write_audit(db, actor_id=user.id, action=action, entity_type="sku",
                entity_id=sku_id, before=before,
                after={"price": str(body.price), "currency": currency,
                       "valid_from": valid_from.isoformat()})
    db.commit()
    return _price_out(db, new_price)
