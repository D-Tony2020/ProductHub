"""成品采购件库（黑盒件）：供应商 + 件名 + 所属部件类型，可被多个 SKU 复用。"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CODE_SQL_CHECK, PkMixin, TimestampMixin


class Supplier(Base, PkMixin, TimestampMixin):
    __tablename__ = "supplier"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 采购元数据（供应商管理 P2）：纯运营信息，不入指纹、可随时改。
    lead_time_days: Mapped[int | None] = mapped_column(Integer)        # 交期（天）
    payment_terms: Mapped[str | None] = mapped_column(String(200))     # 付款条件
    rating: Mapped[int | None] = mapped_column(SmallInteger)           # 评级 1-5 星

    __table_args__ = (
        CheckConstraint(f"code {CODE_SQL_CHECK}", name="code_charset"),
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_non_negative"),
    )


class PurchasedPart(Base, PkMixin, TimestampMixin):
    """黑盒成品件。code 入指纹（不可变）。

    状态机：draft（业务员现场新建，可用于配置）→ active（admin 审核转正）；
    merged（admin 判定重复，指向正件，禁止用于新配置，旧 SKU 不受影响）；
    retired（停用，禁止用于新配置）。
    """

    __tablename__ = "purchased_part"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    node_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_type.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("supplier.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    spec_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    merged_into_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("purchased_part.id", ondelete="RESTRICT")
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL")
    )

    supplier: Mapped[Supplier] = relationship()
    node_type = relationship("NodeType")

    __table_args__ = (
        UniqueConstraint("supplier_id", "node_type_id", "name"),
        # 供 sku_config_node 复合 FK (purchased_part_id, node_type_id) 引用：黑盒件类型必须匹配槽
        UniqueConstraint("id", "node_type_id"),
        CheckConstraint(f"code {CODE_SQL_CHECK}", name="code_charset"),
        CheckConstraint(
            "status IN ('draft', 'active', 'merged', 'retired')", name="status_enum"
        ),
        CheckConstraint(
            "(status = 'merged') = (merged_into_id IS NOT NULL)", name="merged_target"
        ),
    )
