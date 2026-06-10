from datetime import datetime

from sqlalchemy import BigInteger, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一命名约定：迁移可重复、约束名可预测（约束名是红线测试的断言对象）
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

# 所有业务 code 的合法字符集：进入指纹序列化，禁止分隔符注入
CODE_REGEX = r"^[A-Z0-9_-]+$"
CODE_SQL_CHECK = f"~ '{CODE_REGEX}'"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PkMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
