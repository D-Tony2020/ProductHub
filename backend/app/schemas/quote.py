from decimal import Decimal

from pydantic import BaseModel, Field


class QuoteIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    customer_contact: str | None = Field(default=None, max_length=200)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    valid_until: str | None = None
    notes: str | None = None


class QuoteUpdate(BaseModel):
    customer_name: str | None = Field(default=None, max_length=200)
    customer_contact: str | None = Field(default=None, max_length=200)
    valid_until: str | None = None
    notes: str | None = None


class QuoteItemIn(BaseModel):
    sku_id: int
    qty: int = Field(ge=1, le=100_000_000)


class QuoteItemUpdate(BaseModel):
    qty: int | None = Field(default=None, ge=1, le=100_000_000)
    unit_price: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999999.9999"))
    line_note: str | None = Field(default=None, max_length=300)


class QuoteItemOut(BaseModel):
    id: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    qty: int
    snapshot_price: Decimal
    unit_price: Decimal
    line_total: Decimal
    line_note: str | None
    price_changed: bool = False  # 现价与快照不一致（导出前提示）
    current_price: Decimal | None = None
    supply_warnings: list[str] = []  # 加入时该 SKU 的 supply 提醒（含停用/停产件），仅当次回填

    model_config = {"from_attributes": True}


class QuoteOut(BaseModel):
    id: int
    quote_no: str
    customer_name: str
    customer_contact: str | None
    currency: str
    valid_until: str | None = None
    notes: str | None
    status: str
    created_at: str | None = None
    exported_at: str | None = None
    items: list[QuoteItemOut] = []
    total: Decimal = Decimal("0")

    model_config = {"from_attributes": True}


class PriceCheckOut(BaseModel):
    consistent: bool
    changed_items: list[QuoteItemOut]
