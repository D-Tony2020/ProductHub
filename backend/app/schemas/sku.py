from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.config import ConfigPayload, CurrentPrice

HealthStatus = Literal["ok", "incomplete", "supply_warn"]


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
    # 健康状态(M1)：ok / incomplete(红,缺必选或违反互斥) / supply_warn(黄,含停用件)。
    # 由端点实时推导填充，非 ORM 列。
    health_status: HealthStatus | None = None

    model_config = {"from_attributes": True}


class HealthIssue(BaseModel):
    family: Literal["completeness", "structural", "supply"]
    path: str
    message: str
    supply_kind: str | None = None


class HealthFamilies(BaseModel):
    completeness: list[HealthIssue] = []
    structural: list[HealthIssue] = []
    supply: list[HealthIssue] = []


class SkuHealth(BaseModel):
    """SKU 在最新模板下的健康体检（实时推导，不碰指纹）。"""

    sku_id: int
    sku_code: str
    status: HealthStatus
    blocking: bool       # completeness 或 structural 非空 → 不可加入报价单
    quotable: bool       # = not blocking
    families: HealthFamilies


class SkuDetailOut(SkuOut):
    config_tree: SkuNodeOut | None = None
    health: SkuHealth | None = None


class SkuCreateResult(BaseModel):
    created: bool
    sku: SkuOut


class SkuListOut(BaseModel):
    total: int
    items: list[SkuOut]


class SkuStatsOut(BaseModel):
    """SKU 库统计带：货架口径的四个关键数。"""

    active: int          # 在售且有现价（货架上能报的货）
    pending_price: int   # 在售但无现价（待录价工作堆）
    new_this_week: int   # 近 7 天新增的在售 SKU
    stale_30d: int       # 在售有价、现价已生效超过 30 天未动（提醒复审）


class PriceIn(BaseModel):
    # 上限对齐 Numeric(14,4) 容量，超限在入参层拦截而非数据库 500
    price: Decimal = Field(ge=0, le=Decimal("9999999999.9999"))
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
    superseded: bool = False  # 同日纠错被取代的作废行（历史展示灰显，不计现价）


SkuNodeOut.model_rebuild()
