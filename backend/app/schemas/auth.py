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

    model_config = {"from_attributes": True}


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
