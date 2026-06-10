"""价格层：append-only。改价 = 同事务关闭旧记录 valid_to + 插入新记录；禁止 UPDATE price。

EXCLUDE 约束（btree_gist）在数据库层拒绝同 SKU 同币种生效期重叠——并发录价的最终兜底。
应用约定：旧价 valid_to 止于 D-1，新价 valid_from 始于 D（闭区间 daterange '[]'）。
"""
from datetime import date
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
        ),
    )
