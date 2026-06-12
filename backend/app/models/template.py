"""定义层（模板）：品类/部件类型 → 部件槽 → 规格属性 → 选项。

生命周期纪律：code 一旦创建不可变；不做物理删除，只软停用（is_active=False）；
已被 SKU 引用的对象由 FK RESTRICT 兜底删不掉。
"""
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CODE_SQL_CHECK, PkMixin, TimestampMixin


class NodeType(Base, PkMixin, TimestampMixin):
    """品类与部件类型的统一递归抽象（整机品类与"阀门"同构）。"""

    __tablename__ = "node_type"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    is_sellable_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    slots: Mapped[list["ComponentSlot"]] = relationship(
        back_populates="parent_type",
        foreign_keys="ComponentSlot.parent_type_id",
        order_by="ComponentSlot.display_order",
    )
    attributes: Mapped[list["AttributeDef"]] = relationship(
        back_populates="node_type", order_by="AttributeDef.display_order"
    )

    __table_args__ = (
        CheckConstraint(f"code {CODE_SQL_CHECK}", name="code_charset"),
        CheckConstraint("kind IN ('product', 'part')", name="kind_enum"),
    )


class ComponentSlot(Base, PkMixin, TimestampMixin):
    """部件槽：parent 类型拥有的一个部件位置，装 child 类型的部件。槽图必须为 DAG（服务层防环）。"""

    __tablename__ = "component_slot"

    parent_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_type.id", ondelete="RESTRICT"), nullable=False
    )
    child_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_type.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_blackbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 互斥槽组（变体）：同一父类型下同组槽"恰好选配一个"（如喷管总成的「型号」三选一）。
    # 组名仅作分组与展示，不入指纹（被选中槽以自身 code 入指纹，变体天然异指纹）。
    variant_group: Mapped[str | None] = mapped_column(String(50))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    parent_type: Mapped[NodeType] = relationship(
        back_populates="slots", foreign_keys=[parent_type_id]
    )
    child_type: Mapped[NodeType] = relationship(foreign_keys=[child_type_id])

    __table_args__ = (
        UniqueConstraint("parent_type_id", "code"),
        # 供 sku_config_node 复合 FK (slot_id, node_type_id) 引用：数据库层强制"节点类型匹配槽定义"
        UniqueConstraint("id", "child_type_id"),
        CheckConstraint(f"code {CODE_SQL_CHECK}", name="code_charset"),
    )


class AttributeDef(Base, PkMixin, TimestampMixin):
    """规格属性定义。v1 全部 value_kind='enum'：业务员只能选不能填。"""

    __tablename__ = "attribute_def"

    node_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_type.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    value_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="enum")
    unit: Mapped[str | None] = mapped_column(String(20))
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_filterable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    node_type: Mapped[NodeType] = relationship(back_populates="attributes")
    options: Mapped[list["AttributeOption"]] = relationship(
        back_populates="attribute", order_by="AttributeOption.display_order"
    )

    __table_args__ = (
        UniqueConstraint("node_type_id", "code"),
        CheckConstraint(f"code {CODE_SQL_CHECK}", name="code_charset"),
        CheckConstraint("value_kind IN ('enum', 'number', 'text')", name="value_kind_enum"),
    )


class AttributeOption(Base, PkMixin, TimestampMixin):
    """枚举选项。code 入指纹（不可变），label 仅展示（可改）。"""

    __tablename__ = "attribute_option"

    attribute_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attribute_def.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    attribute: Mapped[AttributeDef] = relationship(back_populates="options")

    __table_args__ = (
        UniqueConstraint("attribute_id", "code"),
        # 供 sku_attribute_value 复合 FK (attribute_id, option_id) 引用：数据库层强制"选项属于该属性"
        UniqueConstraint("attribute_id", "id"),
        CheckConstraint(f"code {CODE_SQL_CHECK}", name="code_charset"),
    )
