# -*- coding: utf-8 -*-
"""生成《存量数据导入 Excel 模板》：基于现有测试数据反构出真实可导入的样例行 +
字典/填写说明 sheet，并回灌 dry-run 自证模板可用（行能被导入端点解析、无 RowError）。
模拟客户存量旧数据导入：客户按本模板与字典把旧系统数据映射进来。

导入格式（与 import_service 对齐）：
  固定列 root_type_code | price | currency | valid_from
  属性列 attr:<槽code.槽code.属性code>（根属性直接 attr:属性code），填选项 code 或 label
  黑盒列 part:<槽路径>，填「供应商名|件名」（自动建档/复用）

用法： .venv\\Scripts\\python.exe scripts\\gen_import_template.py
输出： docs/templates/存量数据导入模板.xlsx
"""
import os
os.environ.setdefault(
    "PRODUCTHUB_DATABASE_URL",
    "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub")

import io  # noqa: E402
from pathlib import Path  # noqa: E402

from openpyxl import Workbook  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AttributeDef, AttributeOption, ComponentSlot, NodeType, PurchasedPart,
    Sku, SkuConfigNode, SkuPrice, Supplier,
)
from app.services.health_engine import reconstruct_payload  # noqa: E402
from app.services.import_service import parse_workbook, process_row  # noqa: E402

db = SessionLocal()

# ---- 元数据字典 ----
NT = {n.id: n for n in db.execute(select(NodeType)).scalars()}
ATTR = {a.id: a for a in db.execute(select(AttributeDef)).scalars()}
OPT = {o.id: o for o in db.execute(select(AttributeOption)).scalars()}
SLOT = {s.id: s for s in db.execute(select(ComponentSlot)).scalars()}
SUP = {s.id: s for s in db.execute(select(Supplier)).scalars()}
PP = {p.id: p for p in db.execute(select(PurchasedPart)).scalars()}

ROOT = db.execute(select(NodeType).where(NodeType.name == "干粉灭火器")).scalar_one()


def cur_price(sku_id):
    p = db.execute(select(SkuPrice).where(
        SkuPrice.sku_id == sku_id, SkuPrice.valid_to.is_(None),
        SkuPrice.superseded_at.is_(None)).order_by(SkuPrice.id.desc())).scalars().first()
    return (str(p.price), p.currency) if p else ("", "")


def flatten(payload, sku_id):
    """ConfigPayload → 扁平导入列 dict（attr:/part: 列 + 固定列）。仅处理白盒根。"""
    if payload.root is None:
        return None
    row = {"root_type_code": ROOT.code}
    used_types = {ROOT.id}

    def walk(node, path):
        for a in node.attributes:
            ad = ATTR[a.attribute_id]
            key = "attr:" + (".".join(path) + "." if path else "") + ad.code
            row[key] = OPT[a.option_id].label
        for s in node.slots:
            sl = SLOT[s.slot_id]
            npath = path + [sl.code]
            if s.mode == "purchased" and s.purchased_part_id:
                part = PP.get(s.purchased_part_id)
                if part:
                    sup = SUP.get(part.supplier_id)
                    row["part:" + ".".join(npath)] = f"{sup.name if sup else '?'}|{part.name}"
            elif s.mode == "configured" and s.child is not None:
                used_types.add(sl.child_type_id)
                walk(s.child, npath)

    walk(payload.root, [])
    price, ccy = cur_price(sku_id)
    row["price"], row["currency"], row["valid_from"] = price, ccy, ""
    return row, used_types


# ---- 取若干白盒根 SKU 反构成样例行 ----
sku_ids = db.execute(
    select(Sku.id).where(Sku.root_type_id == ROOT.id, Sku.status == "active")
    .order_by(Sku.id).limit(40)).scalars().all()
rows, all_types = [], {ROOT.id}
for sid in sku_ids:
    s = db.execute(select(Sku).where(Sku.id == sid).options(
        selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))).scalar_one()
    payload = reconstruct_payload(s)
    r = flatten(payload, sid)
    if r is None:
        continue
    row, used = r
    rows.append(row)
    all_types |= used
    if len(rows) >= 6:
        break

# ---- 列序：固定列 + attr: + part: + 价格列 ----
attr_cols, part_cols = set(), set()
for r in rows:
    for k in r:
        if k.startswith("attr:"):
            attr_cols.add(k)
        elif k.startswith("part:"):
            part_cols.add(k)
headers = (["root_type_code"] + sorted(attr_cols) + sorted(part_cols)
           + ["price", "currency", "valid_from"])

# ---- 写 Excel ----
wb = Workbook()
ws = wb.active
ws.title = "导入模板"
ws.append(headers)
for r in rows:
    ws.append([r.get(h, "") for h in headers])

# 字典 sheet
wd = wb.create_sheet("填写说明与字典")
wd.append(["《存量数据导入模板》填写说明"])
wd.append([])
wd.append(["列类型", "含义", "填法"])
wd.append(["root_type_code", "整机品类编码", f"本模板示例品类=干粉灭火器，code={ROOT.code}；多品类分多份或多 sheet"])
wd.append(["attr:<路径>", "某节点的规格属性", "路径=槽code.槽code.属性code（根属性直接 attr:属性code）；单元格填选项 code 或中文 label"])
wd.append(["part:<槽路径>", "黑盒采购成品件", "单元格填「供应商名|件名」；供应商/件不存在则自动建档（务必核对名称口径一致）"])
wd.append(["price/currency/valid_from", "可选录价", "价格数字 / 币种(USD/CNY) / 生效日(YYYY-MM-DD，空=今天)"])
wd.append([])
wd.append(["—— 本模板涉及的品类字典（code → 名称）——"])
for tid in sorted(all_types):
    nt = NT[tid]
    wd.append([nt.code, nt.name, nt.kind])
wd.append([])
wd.append(["—— 属性与选项字典（按涉及的品类）——"])
wd.append(["品类", "属性code", "属性名", "可选选项(code | label)"])
for tid in sorted(all_types):
    for a in db.execute(select(AttributeDef).where(
            AttributeDef.node_type_id == tid, AttributeDef.is_active.is_(True))).scalars():
        opts = db.execute(select(AttributeOption).where(
            AttributeOption.attribute_id == a.id, AttributeOption.is_active.is_(True))).scalars()
        wd.append([NT[tid].name, a.code, a.name,
                   "; ".join(f"{o.code}|{o.label}" for o in opts)])

out_dir = Path("../docs/templates")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "存量数据导入模板.xlsx"
wb.save(out_path)
print(f"WROTE {out_path.resolve()}  rows={len(rows)} cols={len(headers)}")

# ---- 自证：回灌 dry-run，确认每行可被导入端点解析、无 RowError ----
buf = io.BytesIO()
wb.save(buf)
hdrs, parsed = parse_workbook(buf.getvalue())
ok = bad = 0
for item in parsed:
    try:
        res = process_row(db, item["cells"], commit_mode=False, actor_id=None)
        ok += 1
        print(f"  row{item['row_no']}: {res.get('status')} {res.get('matched') or res.get('note') or ''}")
    except Exception as e:
        bad += 1
        print(f"  row{item['row_no']}: ROWERROR {e}")
print(f"SELF-VERIFY dry-run: {ok} ok / {bad} error（应 0 error）")
db.close()
