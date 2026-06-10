"""数据库层红线：复合外键、价格排他、部分唯一索引必须由数据库直接拒绝违规数据。"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Sku, SkuAttributeValue, SkuConfigNode, SkuPrice
from app.services.config_engine import create_sku
from tests.conftest import make_payload


def _make_sku(db, template):
    sku, _ = create_sku(db, make_payload(template), created_by=None)
    db.commit()
    return sku


def test_option_of_wrong_attribute_rejected(db, template):
    """选项挂错属性：复合 FK (attribute_id, option_id) 拒绝。"""
    sku = _make_sku(db, template)
    node = db.query(SkuConfigNode).filter_by(sku_id=sku.id, parent_node_id=None).one()
    wrong = SkuAttributeValue(
        config_node_id=node.id,
        attribute_id=template["material"].id,           # 筒体材质属性
        option_id=template["options"]["BODY.BRASS"].id,  # 却给阀体选项
    )
    db.add(wrong)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_blackbox_part_type_mismatch_rejected(db, template):
    """黑盒件类型与槽不匹配：复合 FK (purchased_part_id, node_type_id) 拒绝。"""
    sku = _make_sku(db, template)
    root = db.query(SkuConfigNode).filter_by(sku_id=sku.id, parent_node_id=None).one()
    bad = SkuConfigNode(
        sku_id=sku.id, parent_node_id=root.id, slot_id=template["slot_cyl"].id,
        node_type_id=template["cyl"].id, mode="purchased",
        purchased_part_id=template["part"].id,  # 阀门件装进筒体槽
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_node_type_must_match_slot(db, template):
    """节点类型与槽定义不符：复合 FK (slot_id, node_type_id) 拒绝。"""
    sku = _make_sku(db, template)
    root = db.query(SkuConfigNode).filter_by(sku_id=sku.id, parent_node_id=None).one()
    bad = SkuConfigNode(
        sku_id=sku.id, parent_node_id=root.id, slot_id=template["slot_cyl"].id,
        node_type_id=template["valve"].id,  # 筒体槽里塞阀门类型
        mode="configured",
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_price_overlap_rejected_by_exclude(db, template):
    """价格生效期重叠：EXCLUDE 约束直接拒绝。"""
    sku = _make_sku(db, template)
    db.add(SkuPrice(sku_id=sku.id, price=10, currency="USD",
                    valid_from=date(2026, 1, 1), valid_to=None))
    db.commit()
    db.add(SkuPrice(sku_id=sku.id, price=12, currency="USD",
                    valid_from=date(2026, 6, 1), valid_to=None))  # 与开放期重叠
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    # 不同币种不冲突
    db.add(SkuPrice(sku_id=sku.id, price=70, currency="CNY",
                    valid_from=date(2026, 1, 1), valid_to=None))
    db.commit()


def test_price_adjacent_days_allowed(db, template):
    """旧价止于 D-1、新价始于 D：闭区间下相邻不重叠。"""
    sku = _make_sku(db, template)
    db.add(SkuPrice(sku_id=sku.id, price=10, currency="USD",
                    valid_from=date(2026, 1, 1), valid_to=date(2026, 5, 31)))
    db.add(SkuPrice(sku_id=sku.id, price=12, currency="USD",
                    valid_from=date(2026, 6, 1), valid_to=None))
    db.commit()


def test_duplicate_fingerprint_rejected_at_db(db, template):
    """绕过服务层直接插入同指纹：唯一索引拒绝。"""
    sku = _make_sku(db, template)
    clone = Sku(sku_code="SKU-FAKE-1", root_type_id=sku.root_type_id,
                fingerprint=sku.fingerprint, name="分身", status="active")
    db.add(clone)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_single_root_per_sku(db, template):
    """每个 SKU 只能有一个根节点：部分唯一索引拒绝第二个根。"""
    sku = _make_sku(db, template)
    second_root = SkuConfigNode(
        sku_id=sku.id, parent_node_id=None, slot_id=None,
        node_type_id=template["ext"].id, mode="configured",
    )
    db.add(second_root)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_purchased_mode_requires_part(db, template):
    """CHECK：mode=purchased 必须挂成品件。"""
    sku = _make_sku(db, template)
    root = db.query(SkuConfigNode).filter_by(sku_id=sku.id, parent_node_id=None).one()
    bad = SkuConfigNode(
        sku_id=sku.id, parent_node_id=root.id, slot_id=template["slot_cyl"].id,
        node_type_id=template["cyl"].id, mode="purchased", purchased_part_id=None,
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
