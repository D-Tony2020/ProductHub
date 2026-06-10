"""人读业务编码：SKU-2026-00001 / PP-2026-0001 / Q-2026-0001。

计数器行用 SELECT ... FOR UPDATE 锁定，并发下编码唯一；编码列另有 UNIQUE 兜底。
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import CodeCounter

_FORMATS = {
    "SKU": ("SKU", 5),
    "PP": ("PP", 4),
    "Q": ("Q", 4),
    "SUP": ("SUP", 4),
}


def next_code(db: Session, kind: str) -> str:
    prefix, width = _FORMATS[kind]
    year = date.today().year
    # 不存在则建行（幂等），随后行锁递增
    db.execute(
        pg_insert(CodeCounter)
        .values(kind=kind, year=year, value=0)
        .on_conflict_do_nothing(index_elements=["kind", "year"])
    )
    counter = db.execute(
        select(CodeCounter)
        .where(CodeCounter.kind == kind, CodeCounter.year == year)
        .with_for_update()
    ).scalar_one()
    counter.value += 1
    return f"{prefix}-{year}-{counter.value:0{width}d}"
