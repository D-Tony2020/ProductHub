from decimal import Decimal

from pydantic import BaseModel, Field

CODE_PATTERN = r"^[A-Z0-9_-]+$"


class NodeTypeIn(BaseModel):
    # code 缺省时由名称拼音自动生成（UI 已不暴露；API 保留显式传入供导入/种子使用）
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern=r"^(product|part)$")
    is_sellable_root: bool = False
    display_order: int = 0


class NodeTypeUpdate(BaseModel):
    # code 不可变：无此字段
    name: str | None = Field(default=None, max_length=100)
    is_sellable_root: bool | None = None
    display_order: int | None = None
    is_active: bool | None = None


class NodeTypeOut(BaseModel):
    id: int
    code: str
    name: str
    kind: str
    is_sellable_root: bool
    display_order: int
    is_active: bool
    sku_count: int | None = None     # 仅 with_counts=true 时填充（该品类在售 SKU 数）
    parent_count: int | None = None  # 仅 with_counts=true 时填充（被几个上级当部件引用）

    model_config = {"from_attributes": True}


class SlotIn(BaseModel):
    child_type_id: int
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    is_required: bool = True
    allow_blackbox: bool = True
    # 互斥槽组（变体三选一等）：同组恰好选配一个；组名仅分组展示，不入指纹
    variant_group: str | None = Field(default=None, max_length=50)
    display_order: int = 0


class SlotUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    is_required: bool | None = None
    allow_blackbox: bool | None = None
    variant_group: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


class SlotOut(BaseModel):
    id: int
    parent_type_id: int
    child_type_id: int
    code: str
    name: str
    is_required: bool
    allow_blackbox: bool
    variant_group: str | None = None
    display_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class AttributeIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    value_kind: str = Field(default="enum", pattern=r"^enum$")  # v1 只开放 enum
    unit: str | None = Field(default=None, max_length=20)
    is_required: bool = True
    is_filterable: bool = False
    display_order: int = 0


class AttributeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=20)
    is_required: bool | None = None
    is_filterable: bool | None = None
    display_order: int | None = None
    is_active: bool | None = None


class AttributeOut(BaseModel):
    id: int
    node_type_id: int
    code: str
    name: str
    value_kind: str
    unit: str | None
    is_required: bool
    is_filterable: bool
    display_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class OptionIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=CODE_PATTERN)
    label: str = Field(min_length=1, max_length=100)
    numeric_value: Decimal | None = None
    display_order: int = 0


class OptionUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    numeric_value: Decimal | None = None
    display_order: int | None = None
    is_active: bool | None = None


class OptionOut(BaseModel):
    id: int
    attribute_id: int
    code: str
    label: str
    numeric_value: Decimal | None
    display_order: int
    is_active: bool
    reference_count: int = 0

    model_config = {"from_attributes": True}


class AttributeWithOptionsOut(AttributeOut):
    options: list[OptionOut] = []


class ParentRefOut(BaseModel):
    id: int
    name: str
    is_active: bool


class NodeTypeDetailOut(NodeTypeOut):
    attributes: list[AttributeWithOptionsOut] = []
    slots: list[SlotOut] = []
    # 反向归属：本节点被哪些上级当部件引用（多对多，直接上级）
    parents: list[ParentRefOut] = []
