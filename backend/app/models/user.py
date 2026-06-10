from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PkMixin, TimestampMixin


class AppUser(Base, PkMixin, TimestampMixin):
    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="sales")
    # 录价权默认仅 admin，可单独授予资深业务员
    can_set_price: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (CheckConstraint("role IN ('admin', 'sales')", name="role_enum"),)
