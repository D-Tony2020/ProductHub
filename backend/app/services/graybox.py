"""灰盒成品件：把件的可选结构化规格(spec_config·ConfigPayload 形态) 渲染成可读摘要。

纯只读、纯展示——规格不入指纹、不入报价，此处只把它翻成人能看的字符串，
供"配置选件展示规格"与"SKU 详情渐进披露"两处复用。
"""
from sqlalchemy.orm import Session

from app.models import AttributeDef, AttributeOption, ComponentSlot, PurchasedPart


def summarize_spec(db: Session, payload: dict | None) -> str:
    """spec_config(可选配置树) → "阀体材质=黄铜；密封圈=丁腈" 形态的可读摘要；空则空串。"""
    if not payload or not payload.get("root"):
        return ""
    parts: list[str] = []

    def walk(node_in: dict, prefix: str = "") -> None:
        for av in node_in.get("attributes", []) or []:
            attr = db.get(AttributeDef, av.get("attribute_id"))
            opt = db.get(AttributeOption, av.get("option_id"))
            if attr and opt:
                parts.append(f"{prefix}{attr.name}={opt.label}")
        for sel in node_in.get("slots", []) or []:
            if not sel or sel.get("mode") == "empty":
                continue
            slot = db.get(ComponentSlot, sel["slot_id"]) if sel.get("slot_id") else None
            sname = slot.name if slot else "部件"
            if sel.get("mode") == "purchased" and sel.get("purchased_part_id"):
                p = db.get(PurchasedPart, sel["purchased_part_id"])
                if p:
                    parts.append(f"{prefix}{sname}={p.name}")
            elif sel.get("mode") == "configured" and sel.get("child"):
                walk(sel["child"], f"{prefix}{sname}·")

    walk(payload["root"])
    return "；".join(parts)
