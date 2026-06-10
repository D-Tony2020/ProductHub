"""配置引擎：模板校验 → 规范化序列化 → SHA-256 指纹 → SKU 落库。

红线保证：
- 同配置必同指纹：属性按 attribute.code 排序、子件按 slot.code 排序、编码只用不可变 code；
- 异配置必异指纹：结构化编码带 "C:/P:" 前缀与 {};|,= 分隔符，code 字符集由 CHECK 约束限定 [A-Z0-9_-]，
  分隔符无法被注入；
- 可选属性未选时不编码（模板端禁止为可选属性建"无"语义选项，见模板管理校验）；
- 仅完整配置可算指纹与落库；落库前服务端独立重算，并发撞车由 sku.fingerprint 唯一索引兜底。
"""
import hashlib
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import (
    AttributeDef,
    AttributeOption,
    NodeType,
    PurchasedPart,
    Sku,
    SkuAttributeValue,
    SkuConfigNode,
    SkuPrice,
    ComponentSlot,
)
from app.schemas.config import (
    ConfigNodeIn,
    ConfigPayload,
    CurrentPrice,
    MatchedSku,
    SlotSelection,
    ValidateResult,
    ValidationIssue,
)
from app.services.codes import next_code


class IncompleteConfigError(Exception):
    """配置不完整或非法，不允许落库。"""

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("config is incomplete or invalid")


@dataclass
class _WalkState:
    issues: list[ValidationIssue] = field(default_factory=list)
    # (节点序列化串, 展示名片段) 仅在该子树完全合法且完整时非 None
    summary_parts: list[str] = field(default_factory=list)

    def error(self, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(path=path, kind="error", message=message))

    def missing(self, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(path=path, kind="missing", message=message))


def _load_type(db: Session, type_id: int) -> NodeType | None:
    return db.execute(
        select(NodeType)
        .where(NodeType.id == type_id)
        .options(
            selectinload(NodeType.attributes).selectinload(AttributeDef.options),
            selectinload(NodeType.slots),
        )
    ).scalar_one_or_none()


def _walk(
    db: Session,
    node_type: NodeType,
    node_in: ConfigNodeIn,
    path: str,
    depth: int,
    state: _WalkState,
) -> str | None:
    """校验一个白盒节点并返回其规范化序列化串；存在问题时返回 None。"""
    settings = get_settings()
    if depth > settings.max_config_depth:
        state.error(path, f"配置层级超过上限 {settings.max_config_depth}")
        return None

    ok = True

    # ---- 属性 ----
    active_attrs = {a.id: a for a in node_type.attributes if a.is_active}
    selected: dict[int, int] = {}
    for sel in node_in.attributes:
        if sel.attribute_id in selected:
            state.error(path, f"属性重复提交（attribute_id={sel.attribute_id}）")
            ok = False
            continue
        selected[sel.attribute_id] = sel.option_id

    for attr_id in selected:
        if attr_id not in active_attrs:
            state.error(path, f"属性不属于该节点类型或已停用（attribute_id={attr_id}）")
            ok = False

    attr_tokens: list[tuple[str, str]] = []  # (attr.code, "code=opt_code")
    for attr in active_attrs.values():
        option_id = selected.get(attr.id)
        if option_id is None:
            if attr.is_required:
                state.missing(path, f"必选属性未选择：{attr.name}")
                ok = False
            continue
        option: AttributeOption | None = next(
            (o for o in attr.options if o.id == option_id), None
        )
        if option is None:
            state.error(path, f"选项不属于属性「{attr.name}」（option_id={option_id}）")
            ok = False
            continue
        if not option.is_active:
            state.error(path, f"选项已停用，不可用于新配置：{attr.name}={option.label}")
            ok = False
            continue
        attr_tokens.append((attr.code, f"{attr.code}={option.code}"))
        state.summary_parts.append(option.label)

    # ---- 部件槽 ----
    active_slots = {s.id: s for s in node_type.slots if s.is_active}
    slot_sel: dict[int, SlotSelection] = {}
    for sel in node_in.slots:
        if sel.slot_id in slot_sel:
            state.error(path, f"部件槽重复提交（slot_id={sel.slot_id}）")
            ok = False
            continue
        slot_sel[sel.slot_id] = sel

    for slot_id in slot_sel:
        if slot_id not in active_slots:
            state.error(path, f"部件槽不属于该节点类型或已停用（slot_id={slot_id}）")
            ok = False

    child_tokens: list[tuple[str, str]] = []  # (slot.code, "slot_code:serial")
    for slot in active_slots.values():
        sel = slot_sel.get(slot.id)
        sub_path = f"{path}/{slot.code}"
        if sel is None or sel.mode == "empty":
            if slot.is_required:
                state.missing(sub_path, f"必配部件未配置：{slot.name}")
                ok = False
            continue

        if sel.mode == "purchased":
            if not slot.allow_blackbox:
                state.error(sub_path, f"部件「{slot.name}」不允许使用成品采购件")
                ok = False
                continue
            part = db.get(PurchasedPart, sel.purchased_part_id) if sel.purchased_part_id else None
            if part is None:
                state.error(sub_path, "成品采购件不存在")
                ok = False
                continue
            if part.node_type_id != slot.child_type_id:
                state.error(sub_path, f"成品件「{part.name}」的部件类型与槽不匹配")
                ok = False
                continue
            if part.status not in ("draft", "active"):
                state.error(sub_path, f"成品件「{part.name}」已合并或停用，不可用于新配置")
                ok = False
                continue
            child_tokens.append((slot.code, f"{slot.code}:P:{part.code}"))
            state.summary_parts.append(part.name)
            continue

        # mode == "configured"
        if sel.child is None:
            state.error(sub_path, f"部件「{slot.name}」选择了逐项配置但未提供配置内容")
            ok = False
            continue
        child_type = _load_type(db, slot.child_type_id)
        if child_type is None or not child_type.is_active:
            state.error(sub_path, f"部件类型不可用（node_type_id={slot.child_type_id}）")
            ok = False
            continue
        child_serial = _walk(db, child_type, sel.child, sub_path, depth + 1, state)
        if child_serial is None:
            ok = False
            continue
        child_tokens.append((slot.code, f"{slot.code}:{child_serial}"))

    if not ok:
        return None

    attrs_str = ";".join(t for _, t in sorted(attr_tokens, key=lambda x: x[0]))
    children_str = ",".join(t for _, t in sorted(child_tokens, key=lambda x: x[0]))
    return f"C:{node_type.code}{{{attrs_str}|{children_str}}}"


def _current_prices(db: Session, sku_id: int) -> list[CurrentPrice]:
    today = date.today()
    rows = db.execute(
        select(SkuPrice)
        .where(
            SkuPrice.sku_id == sku_id,
            SkuPrice.valid_from <= today,
            (SkuPrice.valid_to.is_(None)) | (SkuPrice.valid_to >= today),
        )
        .order_by(SkuPrice.currency)
    ).scalars()
    return [
        CurrentPrice(price=r.price, currency=r.currency, valid_from=r.valid_from.isoformat())
        for r in rows
    ]


def matched_sku_payload(db: Session, sku: Sku) -> MatchedSku:
    return MatchedSku(
        id=sku.id,
        sku_code=sku.sku_code,
        name=sku.name,
        status=sku.status,
        current_prices=_current_prices(db, sku.id),
    )


def validate_config(
    db: Session, payload: ConfigPayload, *, for_creation: bool = False
) -> tuple[ValidateResult, str | None]:
    """校验配置；完整时返回指纹与命中 SKU。无副作用。

    返回 (结果, 摘要名)；摘要名仅在完整时有意义。
    """
    state = _WalkState()
    root_type = _load_type(db, payload.root_type_id)
    if root_type is None or not root_type.is_active:
        state.error("ROOT", "根品类不存在或已停用")
        return ValidateResult(complete=False, issues=state.issues), None
    if not root_type.is_sellable_root:
        state.error("ROOT", f"「{root_type.name}」不可作为可售品类的根")
        return ValidateResult(complete=False, issues=state.issues), None

    serial = _walk(db, root_type, payload.root, "ROOT", 1, state)
    if serial is None:
        return ValidateResult(complete=False, issues=state.issues), None

    fingerprint = hashlib.sha256(serial.encode("utf-8")).hexdigest()
    existing = db.execute(
        select(Sku).where(Sku.fingerprint == fingerprint)
    ).scalar_one_or_none()

    summary = " / ".join(state.summary_parts[:6])
    name = f"{root_type.name}（{summary}）" if summary else root_type.name
    result = ValidateResult(
        complete=True,
        issues=[],
        fingerprint=fingerprint,
        matched_sku=matched_sku_payload(db, existing) if existing else None,
    )
    return result, name[:300]


def _build_nodes(
    db: Session, sku: Sku, node_type_id: int, node_in: ConfigNodeIn,
    parent: SkuConfigNode | None, slot_id: int | None,
) -> SkuConfigNode:
    node = SkuConfigNode(
        sku=sku,
        parent=parent,
        slot_id=slot_id,
        node_type_id=node_type_id,
        mode="configured",
        purchased_part_id=None,
    )
    db.add(node)
    for sel in node_in.attributes:
        node.attribute_values.append(
            SkuAttributeValue(attribute_id=sel.attribute_id, option_id=sel.option_id)
        )
    for sel in node_in.slots:
        if sel.mode == "empty":
            continue
        slot = db.get(ComponentSlot, sel.slot_id)
        if sel.mode == "purchased":
            db.add(
                SkuConfigNode(
                    sku=sku,
                    parent=node,
                    slot_id=sel.slot_id,
                    node_type_id=slot.child_type_id,
                    mode="purchased",
                    purchased_part_id=sel.purchased_part_id,
                )
            )
        else:
            _build_nodes(db, sku, slot.child_type_id, sel.child, node, sel.slot_id)
    return node


def create_sku(
    db: Session,
    payload: ConfigPayload,
    *,
    created_by: int | None,
    import_batch_id: int | None = None,
) -> tuple[Sku, bool]:
    """落库 SKU。返回 (sku, created)。命中既有指纹（含并发撞车）时返回既有 SKU。

    调用方负责事务收尾：本函数内部 flush 不 commit。
    """
    result, name = validate_config(db, payload, for_creation=True)
    if not result.complete:
        raise IncompleteConfigError(result.issues)
    assert result.fingerprint is not None

    if result.matched_sku is not None:
        existing = db.get(Sku, result.matched_sku.id)
        return existing, False

    sku = Sku(
        sku_code=next_code(db, "SKU"),
        root_type_id=payload.root_type_id,
        fingerprint=result.fingerprint,
        name=name or "",
        status="active",
        created_by=created_by,
        import_batch_id=import_batch_id,
    )

    try:
        # SAVEPOINT 必须包住从 add 到 flush 的全过程：构建期间禁用 autoflush，
        # 否则 _build_nodes 里的查询会把 INSERT 提前刷到 SAVEPOINT 之外，
        # 并发撞唯一索引时就会报废整个外层事务
        with db.begin_nested():
            with db.no_autoflush:
                db.add(sku)
                _build_nodes(db, sku, payload.root_type_id, payload.root, None, None)
            db.flush()
    except IntegrityError:
        # 并发撞车：丢弃本会话待插入的对象（否则后续查询 autoflush 会再次 INSERT），
        # 改为返回赢家已落库的 SKU
        for obj in list(db.new):
            db.expunge(obj)
        with db.no_autoflush:
            existing = db.execute(
                select(Sku).where(Sku.fingerprint == result.fingerprint)
            ).scalar_one_or_none()
        if existing is not None:
            return existing, False
        raise
    return sku, True
