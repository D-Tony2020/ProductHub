from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    can_set_price: bool
    is_active: bool
    preferences: dict = {}  # per-user 界面偏好；随 /auth/me 一并下发，免额外往返

    model_config = {"from_attributes": True}


class FacetPref(BaseModel):
    key: str = Field(max_length=40)
    visible: bool = True
    expanded: bool | None = None


class PreferencesIn(BaseModel):
    """per-user 界面偏好（自动保存·全量替换）。白名单字段，未知顶层键丢弃、防脏配置入库。"""

    model_config = {"extra": "ignore"}

    product_facets: list[FacetPref] | None = Field(default=None, max_length=50)
    default_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    default_sort: str | None = Field(
        default=None, pattern=r"^(recent|price_asc|price_desc|created_asc|code|name)$")
    page_size: int | None = Field(default=None, ge=1, le=100)
    default_view: str | None = Field(default=None, pattern=r"^(card|table)$")


class UserCreateIn(BaseModel):
    username: str = Field(min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    role: str = Field(pattern=r"^(admin|sales)$")
    can_set_price: bool = False


class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, pattern=r"^(admin|sales)$")
    can_set_price: bool | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
