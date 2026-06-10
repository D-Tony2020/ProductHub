from pydantic import BaseModel, Field

from app.schemas.template import CODE_PATTERN


class SupplierIn(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=200)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class SupplierOut(BaseModel):
    id: int
    code: str
    name: str
    contact: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class PurchasedPartIn(BaseModel):
    node_type_id: int
    supplier_id: int | None = None
    new_supplier_name: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    spec_note: str | None = None


class PurchasedPartUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    spec_note: str | None = None


class PurchasedPartOut(BaseModel):
    id: int
    code: str
    node_type_id: int
    node_type_name: str = ""
    supplier_id: int
    supplier_name: str = ""
    name: str
    spec_note: str | None
    status: str
    merged_into_id: int | None
    reference_count: int = 0

    model_config = {"from_attributes": True}


class MergeIn(BaseModel):
    target_part_id: int


class SimilarQuery(BaseModel):
    node_type_id: int
    name: str
