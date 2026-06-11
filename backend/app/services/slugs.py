"""code 自动生成：中文名 → 拼音大写下划线 slug，作用域内查重加序号。

设计取舍（参考 Salesforce API Name / Akeneo attribute code 的做法）：
- code 仍是不可变的稳定标识（入指纹），但不再要求人工填写；
- 由名称转写生成保证可读性（导入模板列头、日志、跨环境排查都受益）；
- API 仍接受显式 code（导入/种子/我方运维可控场景），UI 不再暴露。
"""
import re

from pypinyin import lazy_pinyin
from sqlalchemy import select
from sqlalchemy.orm import Session

_MAX_BASE_LEN = 40  # 给冲突后缀留余量（列宽 50）


def slugify_name(name: str) -> str:
    parts = lazy_pinyin(name)
    raw = "_".join(p for p in parts if p)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()
    return (slug or "ITEM")[:_MAX_BASE_LEN]


def unique_code(db: Session, model, name: str, *scope_filters) -> str:
    """生成在给定作用域内唯一的 code；冲突时追加 _2/_3…。

    scope_filters：额外的 where 条件（如 AttributeOption.attribute_id == X）；
    并发兜底仍由数据库唯一约束负责，此处冲突重试在调用方的 IntegrityError 分支。
    """
    base = slugify_name(name)
    candidate = base
    seq = 1
    while True:
        stmt = select(model.id).where(model.code == candidate, *scope_filters).limit(1)
        if db.execute(stmt).scalar_one_or_none() is None:
            return candidate
        seq += 1
        candidate = f"{base}_{seq}"
