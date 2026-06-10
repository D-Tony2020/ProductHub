"""导入批次：两阶段（dry_run → committed），file_hash 对已提交批次幂等。"""
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PkMixin, TimestampMixin


class ImportBatch(Base, PkMixin, TimestampMixin):
    __tablename__ = "import_batch"

    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="dry_run")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ok_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_json: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('dry_run', 'committed', 'failed')", name="status_enum"
        ),
        # 同一文件只允许提交一次（dry_run 可重复）
        Index(
            "uq_import_batch_committed_file",
            "file_hash",
            unique=True,
            postgresql_where="status = 'committed'",
        ),
    )
