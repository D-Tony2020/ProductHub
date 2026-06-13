"""开发用冒烟：对既有 SKU 跑健康体检 + 验证黄金不变量（重算指纹==原指纹）。"""
import hashlib

from app.core.db import SessionLocal
from app.models import Sku
from app.services.config_engine import _load_type, _walk, _WalkState
from app.services.health_engine import compute_health, load_sku_for_health, reconstruct_payload


def main() -> None:
    db = SessionLocal()
    import json

    ids = [s.id for s in db.query(Sku).all()]
    print("dev 库 SKU:", ids)
    for sid in ids[:1]:
        sku = load_sku_for_health(db, sid)
        print(f"  节点数={len(list(sku.nodes))}")
        payload = reconstruct_payload(sku)
        print("  reconstruct payload:", json.dumps(payload.model_dump(), ensure_ascii=False)[:600])
        h = compute_health(db, sku)
        print("  completeness:", [i.message for i in h.families.completeness])
    for sid in ids:
        sku = load_sku_for_health(db, sid)
        h = compute_health(db, sku)
        print(f"  {sku.sku_code}: status={h.status} blocking={h.blocking} "
              f"comp={len(h.families.completeness)} struct={len(h.families.structural)} "
              f"supply={len(h.families.supply)}")

    # 黄金不变量：对一个【完整】SKU，reconstruct→重算指纹应 == 原指纹（造完即回滚不留库）
    from app.schemas.config import AttributeSelection, ConfigNodeIn, ConfigPayload
    from app.services.config_engine import create_sku

    d = _load_type(db, 25)  # CO2筒体：纯属性、无必配子槽
    attrs = [AttributeSelection(attribute_id=a.id, option_id=a.options[0].id)
             for a in d.attributes if a.is_active]
    p = ConfigPayload(root_type_id=25, root=ConfigNodeIn(attributes=attrs, slots=[]))
    sku2, _ = create_sku(db, p, created_by=None)
    db.flush()
    db.refresh(sku2)
    h2 = compute_health(db, sku2)
    payload2 = reconstruct_payload(sku2)
    st = _WalkState()
    rt = _load_type(db, payload2.root_type_id)
    serial = _walk(db, rt, payload2.root, "ROOT", 1, st, lenient=True)
    fp = hashlib.sha256(serial.encode()).hexdigest() if serial else None
    print(f"  [黄金] 完整SKU status={h2.status} 指纹不变={fp == sku2.fingerprint}")
    db.rollback()  # 不留测试数据
    db.close()


if __name__ == "__main__":
    main()
