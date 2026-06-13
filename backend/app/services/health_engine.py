"""SKU 健康体检（M1）：把已落库配置树反推成 ConfigPayload，喂 validate_config(lenient)
按最新模板重算完整性，分三族——completeness/structural(红、拦报价) 与 supply(黄、提醒)。

红线：全程只读、绝不碰指纹、不写库。完整性是"模板的函数"，模板一变全量旧 SKU 同时翻面，
故纯实时推导（效仿 pending_price），不物化。
"""
from sqlalchemy.orm import Session, selectinload

from app.models import Sku, SkuConfigNode
from app.schemas.config import (
    AttributeSelection,
    ConfigNodeIn,
    ConfigPayload,
    SlotSelection,
)
from app.schemas.sku import HealthFamilies, HealthIssue, SkuHealth
from app.services.config_engine import validate_config


def load_sku_for_health(db: Session, sku_id: int) -> Sku | None:
    """带 reconstruct 所需的整树关系一次取回，避免 N+1。"""
    return (
        db.query(Sku)
        .options(selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))
        .filter(Sku.id == sku_id)
        .one_or_none()
    )


def reconstruct_payload(sku: Sku) -> ConfigPayload:
    """已落库配置树 → ConfigPayload（复用 config schema，不另建）。纯只读。

    覆盖三种节点形态：configured(白盒,含属性+子槽)、purchased(黑盒,挂成品件)、
    variant(无独立 mode，按已选子节点还原即可，组语义由 validate 重新对照 variant_group)。
    """
    nodes = list(sku.nodes)
    by_parent: dict[int, list[SkuConfigNode]] = {}
    root: SkuConfigNode | None = None
    for n in nodes:
        if n.parent_node_id is None:
            root = n
        else:
            by_parent.setdefault(n.parent_node_id, []).append(n)
    if root is None:
        # 无根=数据异常；返回空配置让 validate 报缺（不应发生）
        return ConfigPayload(root_type_id=sku.root_type_id, root=ConfigNodeIn())

    def to_node_in(node: SkuConfigNode) -> ConfigNodeIn:
        attrs = [
            AttributeSelection(attribute_id=av.attribute_id, option_id=av.option_id)
            for av in node.attribute_values
        ]
        slots = []
        for child in by_parent.get(node.id, []):
            if child.mode == "purchased":
                slots.append(SlotSelection(
                    slot_id=child.slot_id, mode="purchased",
                    purchased_part_id=child.purchased_part_id,
                ))
            else:
                slots.append(SlotSelection(
                    slot_id=child.slot_id, mode="configured", child=to_node_in(child),
                ))
        return ConfigNodeIn(attributes=attrs, slots=slots)

    return ConfigPayload(root_type_id=root.node_type_id, root=to_node_in(root))


def compute_health(db: Session, sku: Sku, type_cache: dict | None = None) -> SkuHealth:
    """对一个已落库 SKU 跑健康体检，返回三族分桶。唯一权威来源：列表/统计/报价闸/详情共用。

    type_cache：批量场景（列表/统计）传入一个共享 dict，跨 SKU 复用类型查询防 N+1。
    """
    payload = reconstruct_payload(sku)
    result, _ = validate_config(db, payload, lenient=True, type_cache=type_cache)

    fam = HealthFamilies()
    for issue in result.issues:
        hi = HealthIssue(
            family=issue.family or "structural",
            path=issue.path,
            message=(issue.message if issue.family
                     else f"数据异常，请联系管理员：{issue.message}"),
            supply_kind=issue.supply_kind,
        )
        # family=None 的兜底（payload 非法/reconstruct 异常）：宁可错拦不可错放 → structural
        getattr(fam, hi.family).append(hi)

    blocking = bool(fam.completeness or fam.structural)
    status = "incomplete" if blocking else ("supply_warn" if fam.supply else "ok")
    return SkuHealth(
        sku_id=sku.id, sku_code=sku.sku_code,
        status=status, blocking=blocking, quotable=not blocking, families=fam,
    )
