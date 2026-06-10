"""实例层：SKU = 一次完整选配；配置树节点白盒（继续拆解）或黑盒（成品件终止）。

数据红线落点：
- sku.fingerprint 全量唯一（含 retired）——同配置绝不出现两个 SKU；
- 复合 FK 在数据库层强制"节点类型匹配槽定义""黑盒件类型匹配槽""选项属于该属性"。
"""
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin


class Sku(Base, PkMixin, TimestampMixin):
    __tablename__ = "sku"

    sku_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    root_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_type.id", ondelete="RESTRICT"), nullable=False
    )
    # SHA-256 hex。全量唯一（含 retired）：作废后重配同款 → 引导恢复原 SKU，杜绝分身
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL")
    )
    import_batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("import_batch.id", ondelete="SET NULL")
    )

    root_type = relationship("NodeType")
    nodes: Mapped[list["SkuConfigNode"]] = relationship(
        back_populates="sku", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'retired')", name="status_enum"),
    )


class SkuConfigNode(Base, PkMixin):
    __tablename__ = "sku_config_node"

    sku_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sku.id", ondelete="CASCADE"), nullable=False
    )
    parent_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sku_config_node.id", ondelete="CASCADE")
    )
    slot_id: Mapped[int | None] = mapped_column(BigInteger)
    node_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_type.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    purchased_part_id: Mapped[int | None] = mapped_column(BigInteger)

    sku: Mapped[Sku] = relationship(back_populates="nodes")
    parent: Mapped["SkuConfigNode | None"] = relationship(
        remote_side="SkuConfigNode.id", back_populates="children"
    )
    children: Mapped[list["SkuConfigNode"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan", passive_deletes=True
    )
    attribute_values: Mapped[list["SkuAttributeValue"]] = relationship(
        back_populates="config_node", cascade="all, delete-orphan", passive_deletes=True
    )
    purchased_part = relationship(
        "PurchasedPart", primaryjoin="SkuConfigNode.purchased_part_id == PurchasedPart.id",
        foreign_keys=[purchased_part_id], viewonly=True,
    )
    slot = relationship(
        "ComponentSlot", primaryjoin="SkuConfigNode.slot_id == ComponentSlot.id",
        foreign_keys=[slot_id], viewonly=True,
    )

    __table_args__ = (
        # 根节点无槽，非根必有槽
        CheckConstraint(
            "(parent_node_id IS NULL) = (slot_id IS NULL)", name="root_no_slot"
        ),
        CheckConstraint("mode IN ('configured', 'purchased')", name="mode_enum"),
        # 黑盒当且仅当挂了成品件
        CheckConstraint(
            "(mode = 'purchased') = (purchased_part_id IS NOT NULL)",
            name="purchased_part_presence",
        ),
        # 同一父节点同一槽只能有一个子节点（PG 默认 NULLS DISTINCT，根行不受此约束）
        UniqueConstraint("sku_id", "parent_node_id", "slot_id"),
        # 每个 SKU 只有一个根节点
        Index(
            "uq_sku_config_node_single_root",
            "sku_id",
            unique=True,
            postgresql_where="parent_node_id IS NULL",
        ),
        # 数据库层强制：子节点类型必须匹配槽定义的 child_type
        ForeignKeyConstraint(
            ["slot_id", "node_type_id"],
            ["component_slot.id", "component_slot.child_type_id"],
            ondelete="RESTRICT",
            name="fk_node_slot_type_match",
        ),
        # 数据库层强制：黑盒件的部件类型必须匹配本节点类型
        ForeignKeyConstraint(
            ["purchased_part_id", "node_type_id"],
            ["purchased_part.id", "purchased_part.node_type_id"],
            ondelete="RESTRICT",
            name="fk_node_part_type_match",
        ),
    )


class SkuAttributeValue(Base, PkMixin):
    __tablename__ = "sku_attribute_value"

    config_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sku_config_node.id", ondelete="CASCADE"), nullable=False
    )
    attribute_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    option_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    config_node: Mapped[SkuConfigNode] = relationship(back_populates="attribute_values")
    attribute = relationship(
        "AttributeDef", primaryjoin="SkuAttributeValue.attribute_id == AttributeDef.id",
        foreign_keys=[attribute_id], viewonly=True,
    )
    option = relationship(
        "AttributeOption", primaryjoin="SkuAttributeValue.option_id == AttributeOption.id",
        foreign_keys=[option_id], viewonly=True,
    )

    __table_args__ = (
        UniqueConstraint("config_node_id", "attribute_id"),
        # 数据库层强制：选项必须属于该属性
        ForeignKeyConstraint(
            ["attribute_id", "option_id"],
            ["attribute_option.attribute_id", "attribute_option.id"],
            ondelete="RESTRICT",
            name="fk_value_option_of_attribute",
        ),
    )


class ConfigDraft(Base, PkMixin, TimestampMixin):
    """配置草稿：半成品选配。非 SKU、无编码、不参与指纹与报价，jsonb 存前端选择集。"""

    __tablename__ = "config_draft"

    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    root_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_type.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
