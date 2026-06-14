"""配置树的传输格式：/config/validate 与 POST /skus 共用。"""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class AttributeSelection(BaseModel):
    attribute_id: int
    option_id: int


class SlotSelection(BaseModel):
    slot_id: int
    mode: Literal["configured", "purchased", "empty"] = "empty"
    child: "ConfigNodeIn | None" = None
    purchased_part_id: int | None = None


class ConfigNodeIn(BaseModel):
    attributes: list[AttributeSelection] = Field(default_factory=list)
    slots: list[SlotSelection] = Field(default_factory=list)
    # 采购溯源(方案甲)：本(白盒)节点的供应商；非必选，设了则 code 入指纹（身份）。
    supplier_id: int | None = None


class ConfigPayload(BaseModel):
    root_type_id: int
    root: ConfigNodeIn


class ValidationIssue(BaseModel):
    path: str  # 槽 code 路径，如 "ROOT/VALVE"
    kind: Literal["error", "missing"]
    message: str
    # 健康检测三族标注（M1）：缺必选/必配=completeness，违反互斥组=structural，
    # 用了停用/合并件=supply；None=数据异常（compute_health 兜底归 structural）。
    family: Literal["completeness", "structural", "supply"] | None = None
    # 仅 supply 族填：区分停用选项/停用部件/已合并/已停用件/停用供应商，供前端文案分流。
    supply_kind: (
        Literal[
            "option_disabled", "part_disabled", "part_merged", "part_retired",
            "supplier_disabled",
        ] | None
    ) = None


class CurrentPrice(BaseModel):
    price: Decimal
    currency: str
    valid_from: str


class MatchedSku(BaseModel):
    id: int
    sku_code: str
    name: str
    status: str
    current_prices: list[CurrentPrice]


class ValidateResult(BaseModel):
    complete: bool
    issues: list[ValidationIssue]
    fingerprint: str | None = None
    matched_sku: MatchedSku | None = None


SlotSelection.model_rebuild()
