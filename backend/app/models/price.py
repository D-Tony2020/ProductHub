"""价格层：append-only。改价 = 同事务关闭旧记录 valid_to + 插入新记录；禁止 UPDATE price。

EXCLUDE 约束（btree_gist，部分约束 WHERE superseded_at IS NULL）拒绝同 SKU 同币种
生效期重叠——并发录价的最终兜底。
- 跨日改价：旧价 valid_to 止于 D-1，新价 valid_from 始于 D（闭区间 daterange '[]'）。
- 同日纠错：旧行软作废（superseded_at 置时间戳、superseded_by 指向新行），物理保留可追溯；
  作废行退出 EXCLUDE 判定，故能与同日新行共存（真 append-only，不再物删）。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin


class SkuPrice(Base, PkMixin, TimestampMixin):
    __tablename__ = "sku_price"

    sku_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sku.id", ondelete="RESTRICT"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL")
    )
    # 软作废（同日纠错）：非空=该行已被同日新价取代，退出现价取数与 EXCLUDE 判定
    superseded_at: Mapped[datetime | None] = mapped_column()
    superseded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sku_price.id", ondelete="SET NULL")
    )

    sku = relationship("Sku")

    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="valid_range_order"
        ),
        ExcludeConstraint(
            (text("sku_id"), "="),
            (text("currency"), "="),
            (text("daterange(valid_from, valid_to, '[]')"), "&&"),
            name="excl_sku_price_overlap",
            using="gist",
            where=text("superseded_at IS NULL"),
        ),
    )
