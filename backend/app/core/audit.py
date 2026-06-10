"""审计写入：与业务变更同事务（调用方 flush/commit 时一并落库）。"""
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    before: dict | None = None,
    after: dict | None = None,
    note: str | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before_json=before,
            after_json=after,
            note=note,
            ip=ip,
        )
    )
