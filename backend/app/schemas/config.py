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


class ConfigPayload(BaseModel):
    root_type_id: int
    root: ConfigNodeIn


class ValidationIssue(BaseModel):
    path: str  # 槽 code 路径，如 "ROOT/VALVE"
    kind: Literal["error", "missing"]
    message: str


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
