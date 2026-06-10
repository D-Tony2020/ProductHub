"""业务编码计数器：SKU-/PP-/Q- 等人读编码的按年流水，行锁保证并发唯一。"""
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CodeCounter(Base):
    __tablename__ = "code_counter"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
