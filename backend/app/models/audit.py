"""审计日志：append-only，与业务变更同事务写入（service 层）。"""
from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PkMixin, TimestampMixin


class AuditLog(Base, PkMixin, TimestampMixin):
    __tablename__ = "audit_log"

    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSONB)
    after_json: Mapped[dict | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(500))
    ip: Mapped[str | None] = mapped_column(String(45))
