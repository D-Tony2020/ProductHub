"""报价单：多草稿并存；单据内禁混币种（应用层）；明细单价为加入时快照；导出后冻结。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin


class Quote(Base, PkMixin, TimestampMixin):
    __tablename__ = "quote"

    quote_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_contact: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL")
    )
    exported_at: Mapped[datetime | None] = mapped_column()

    items: Mapped[list["QuoteItem"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", passive_deletes=True,
        order_by="QuoteItem.id",
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'exported')", name="status_enum"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
    )


class QuoteItem(Base, PkMixin, TimestampMixin):
    __tablename__ = "quote_item"

    quote_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quote.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sku.id", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    # 加入时的现价快照；手动覆盖时 unit_price 改变而 snapshot_price 保留，差异留痕可审计
    snapshot_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    line_note: Mapped[str | None] = mapped_column(String(300))

    quote: Mapped[Quote] = relationship(back_populates="items")
    sku = relationship("Sku")

    __table_args__ = (
        UniqueConstraint("quote_id", "sku_id"),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    )
