"""指纹性质测试：同配置必同指纹、异配置必异指纹、完整性门禁。"""
import pytest

from app.services.config_engine import IncompleteConfigError, create_sku, validate_config
from tests.conftest import make_payload


def test_same_config_any_order_same_fingerprint(db, template):
    r1, _ = validate_config(db, make_payload(template))
    r2, _ = validate_config(db, make_payload(template, attr_order_reversed=True))
    assert r1.complete and r2.complete
    assert r1.fingerprint == r2.fingerprint


def test_option_change_changes_fingerprint(db, template):
    r1, _ = validate_config(db, make_payload(template, charge="KG4"))
    r2, _ = validate_config(db, make_payload(template, charge="KG8"))
    assert r1.fingerprint != r2.fingerprint


def test_blackbox_vs_whitebox_different_fingerprint(db, template):
    r1, _ = validate_config(db, make_payload(template, valve_mode="purchased"))
    r2, _ = validate_config(db, make_payload(template, valve_mode="configured"))
    assert r1.complete and r2.complete
    assert r1.fingerprint != r2.fingerprint


def test_incomplete_config_no_fingerprint(db, template):
    payload = make_payload(template)
    payload.root.attributes = payload.root.attributes[:1]  # 缺工作压力
    result, _ = validate_config(db, payload)
    assert not result.complete
    assert result.fingerprint is None
    assert any(i.kind == "missing" for i in result.issues)


def test_incomplete_cannot_create_sku(db, template):
    payload = make_payload(template)
    payload.root.slots = payload.root.slots[:1]  # 缺必配阀门槽
    with pytest.raises(IncompleteConfigError):
        create_sku(db, payload, created_by=template["admin"].id)


def test_duplicate_create_returns_existing(db, template):
    sku1, created1 = create_sku(db, make_payload(template), created_by=template["admin"].id)
    db.commit()
    sku2, created2 = create_sku(
        db, make_payload(template, attr_order_reversed=True), created_by=template["admin"].id
    )
    db.commit()
    assert created1 is True
    assert created2 is False
    assert sku1.id == sku2.id


def test_concurrent_same_config_single_sku(template):
    """并发兜底：两个独立会话同时落同配置，最终只有一个 SKU。"""
    import threading

    from app.core.db import SessionLocal
    from sqlalchemy import select, func
    from app.models import Sku

    results = []
    barrier = threading.Barrier(2)

    def worker():
        session = SessionLocal()
        try:
            barrier.wait()
            sku, created = create_sku(
                session, make_payload(template), created_by=None
            )
            session.commit()
            results.append((sku.sku_code, created))
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    session = SessionLocal()
    try:
        count = session.execute(select(func.count()).select_from(Sku)).scalar_one()
    finally:
        session.close()
    assert count == 1, f"并发创建产生了 {count} 个 SKU"
    assert sorted(c for _, c in results) in ([False, True], [False, False])


def test_label_rename_keeps_fingerprint(db, template):
    """模板演化：改 label 不改指纹。"""
    before, _ = validate_config(db, make_payload(template))
    opt = template["options"]["CHARGE.KG4"]
    opt.label = "4 公斤（改名）"
    db.commit()
    after, _ = validate_config(db, make_payload(template))
    assert before.fingerprint == after.fingerprint


def test_deactivated_option_rejected_for_new_config(db, template):
    """模板演化：停用选项后新配置不可用，但既有 SKU 不受影响。"""
    sku, _ = create_sku(db, make_payload(template), created_by=template["admin"].id)
    db.commit()
    stored_fingerprint = sku.fingerprint

    template["options"]["CHARGE.KG4"].is_active = False
    db.commit()

    result, _ = validate_config(db, make_payload(template))
    assert not result.complete
    assert any("停用" in i.message for i in result.issues)

    db.refresh(sku)
    assert sku.fingerprint == stored_fingerprint  # 既有 SKU 指纹永不漂移
