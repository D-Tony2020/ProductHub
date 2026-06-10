from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.config import ConfigPayload, CurrentPrice


class SkuCreateIn(BaseModel):
    config: ConfigPayload


class SkuAttributeValueOut(BaseModel):
    attribute_id: int
    option_id: int
    attribute_code: str
    attribute_name: str
    option_code: str
    option_label: str
    option_active: bool


class SkuNodeOut(BaseModel):
    id: int
    slot_id: int | None
    slot_code: str | None
    slot_name: str | None
    node_type_id: int
    node_type_code: str
    node_type_name: str
    mode: str
    purchased_part_id: int | None = None
    purchased_part_name: str | None = None
    supplier_name: str | None = None
    attributes: list[SkuAttributeValueOut] = []
    children: list["SkuNodeOut"] = []


class SkuOut(BaseModel):
    id: int
    sku_code: str
    name: str
    status: str
    root_type_id: int
    root_type_name: str = ""
    fingerprint: str
    current_prices: list[CurrentPrice] = []
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class SkuDetailOut(SkuOut):
    config_tree: SkuNodeOut | None = None


class SkuCreateResult(BaseModel):
    created: bool
    sku: SkuOut


class SkuListOut(BaseModel):
    total: int
    items: list[SkuOut]


class PriceIn(BaseModel):
    price: Decimal = Field(ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    valid_from: str | None = None  # ISO 日期；缺省=今天
    note: str | None = Field(default=None, max_length=500)


class PriceOut(BaseModel):
    id: int
    price: Decimal
    currency: str
    valid_from: str
    valid_to: str | None
    note: str | None
    created_by_name: str | None = None
    created_at: str | None = None


SkuNodeOut.model_rebuild()
