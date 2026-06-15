from pydantic import BaseModel, Field

from app.schemas.template import CODE_PATTERN


class SupplierIn(BaseModel):
    # code 缺省由后端按 SUP 流水自动生成（UI 不暴露）；保留显式传入供导入/种子
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    payment_terms: str | None = Field(default=None, max_length=200)
    rating: int | None = Field(default=None, ge=1, le=5)


class SupplierUpdate(BaseModel):
    # code 不可变（已入指纹·红线）：无此字段
    name: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    payment_terms: str | None = Field(default=None, max_length=200)
    rating: int | None = Field(default=None, ge=1, le=5)


class SupplierOut(BaseModel):
    id: int
    code: str
    name: str
    contact: str | None
    is_active: bool
    lead_time_days: int | None = None
    payment_terms: str | None = None
    rating: int | None = None

    model_config = {"from_attributes": True}


class SupplierOverviewOut(SupplierOut):
    """供应商 + 用量指标（采购侧关心：采购项/整机供应/部件供应/关联成品）。"""

    procurement_items: int = 0   # 采购项数（在用成品采购件）
    assembly_count: int = 0      # 整机供应（product 类型的件）
    component_count: int = 0     # 部件供应（part 类型的件）
    linked_skus: int = 0         # 关联在售 SKU（黑盒 ∪ 白盒来源，去重）


class PurchasedPartIn(BaseModel):
    node_type_id: int
    supplier_id: int | None = None
    new_supplier_name: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    spec_note: str | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)  # 缺省由供应商默认预填


class PurchasedPartUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    spec_note: str | None = None
    spec_config: dict | None = None  # 灰盒结构化规格(可选配置树)；传入即覆盖
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)


class PurchasedPartOut(BaseModel):
    id: int
    code: str
    node_type_id: int
    node_type_name: str = ""
    node_type_kind: str = ""   # product=整机 / part=部件，供前端区分整机直采
    supplier_id: int
    supplier_name: str = ""
    name: str
    spec_note: str | None
    spec_config: dict | None = None   # 灰盒结构化规格
    spec_summary: str = ""            # spec_config 渲染的可读摘要（展示用）
    lead_time_days: int | None = None  # 参考交期(天)
    status: str
    merged_into_id: int | None
    reference_count: int = 0

    model_config = {"from_attributes": True}


class PartSpecUpdate(BaseModel):
    """仅灰盒规格(spec_note/spec_config)，对所有登录用户开放(规格仅描述、不入指纹)。"""

    spec_note: str | None = None
    spec_config: dict | None = None


class LinkedSku(BaseModel):
    id: int
    sku_code: str
    name: str
    status: str


class PurchasedPartDetailOut(PurchasedPartOut):
    """采购件详情页：在列表字段之上带关联在售 SKU 列表。"""

    linked_skus: list[LinkedSku] = []


class MergeIn(BaseModel):
    target_part_id: int


class SimilarQuery(BaseModel):
    node_type_id: int
    name: str
