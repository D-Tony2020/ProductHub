"""互斥槽组（变体）：同组恰好选配一个；不同变体异指纹；组判定取代单槽必配。"""
import pytest

from app.models import AttributeDef, AttributeOption, ComponentSlot, NodeType
from app.schemas.config import (
    AttributeSelection,
    ConfigNodeIn,
    ConfigPayload,
    SlotSelection,
)
from app.services.config_engine import validate_config


@pytest.fixture()
def variant_template(db, template):
    """喷管总成式结构：根类型下「型号」组两个变体槽（喷头型 / 软管+喷头型）。"""
    root = NodeType(code="SPRAY", name="喷管总成T", kind="product", is_sellable_root=True)
    head = NodeType(code="HEAD_V", name="喷头型T", kind="part")
    hose = NodeType(code="HOSE_V", name="软管喷头型T", kind="part")
    db.add_all([root, head, hose])
    db.flush()

    mat = AttributeDef(node_type_id=head.id, code="MAT", name="材质")
    hose_mat = AttributeDef(node_type_id=hose.id, code="HOSE_MAT", name="软管材质")
    db.add_all([mat, hose_mat])
    db.flush()
    o_cu = AttributeOption(attribute_id=mat.id, code="CU", label="铜")
    o_pvc = AttributeOption(attribute_id=hose_mat.id, code="PVC", label="PVC")
    db.add_all([o_cu, o_pvc])

    s_head = ComponentSlot(parent_type_id=root.id, child_type_id=head.id,
                           code="V_HEAD", name="喷头型", variant_group="型号")
    s_hose = ComponentSlot(parent_type_id=root.id, child_type_id=hose.id,
                           code="V_HOSE", name="软管+喷头型", variant_group="型号")
    db.add_all([s_head, s_hose])
    db.commit()
    return {"root": root, "head": head, "hose": hose, "mat": mat, "hose_mat": hose_mat,
            "o_cu": o_cu, "o_pvc": o_pvc, "s_head": s_head, "s_hose": s_hose}


def _payload(t, *, head=False, hose=False):
    slots = []
    if head:
        slots.append(SlotSelection(
            slot_id=t["s_head"].id, mode="configured",
            child=ConfigNodeIn(attributes=[
                AttributeSelection(attribute_id=t["mat"].id, option_id=t["o_cu"].id)]),
        ))
    if hose:
        slots.append(SlotSelection(
            slot_id=t["s_hose"].id, mode="configured",
            child=ConfigNodeIn(attributes=[
                AttributeSelection(attribute_id=t["hose_mat"].id, option_id=t["o_pvc"].id)]),
        ))
    return ConfigPayload(root_type_id=t["root"].id, root=ConfigNodeIn(slots=slots))


def test_group_requires_exactly_one(db, variant_template):
    t = variant_template
    # 0 个：缺「型号」
    r, _ = validate_config(db, _payload(t))
    assert not r.complete
    assert any("型号" in i.message and i.kind == "missing" for i in r.issues)
    # 2 个：错误
    r, _ = validate_config(db, _payload(t, head=True, hose=True))
    assert not r.complete
    assert any("只能选择一种" in i.message for i in r.issues)


def test_each_variant_completes_with_distinct_fingerprint(db, variant_template):
    t = variant_template
    r1, _ = validate_config(db, _payload(t, head=True))
    r2, _ = validate_config(db, _payload(t, hose=True))
    assert r1.complete and r2.complete
    assert r1.fingerprint != r2.fingerprint


def test_grouped_slot_required_flag_not_double_counted(db, variant_template):
    """组内槽默认 is_required=True，但空组只报组级缺失，不再按单槽各报一条。"""
    t = variant_template
    r, _ = validate_config(db, _payload(t))
    slot_level = [i for i in r.issues if "必配部件未配置" in i.message]
    assert not slot_level
