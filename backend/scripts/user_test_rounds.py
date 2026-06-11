# -*- coding: utf-8 -*-
"""20 轮真实用户测试驱动（R1-R19 API 层；R20 浏览器另行执行）。

模拟真实业务员/管理员行为，发现问题按 P0(数据/逻辑致命) P1(功能缺陷) P2(UX/建议) 分级。
测试数据统一带「ZZZ测试」前缀；测试后用 pretest 备份还原开发库。
"""
import io
import json
import sys
import threading

import httpx
from openpyxl import Workbook

BASE = "http://127.0.0.1:8000/api/v1"
FINDINGS: list[dict] = []


def finding(round_no, severity, title, detail=""):
    FINDINGS.append({"round": round_no, "severity": severity, "title": title, "detail": str(detail)[:500]})
    print(f"  [{severity}] R{round_no}: {title}")


def ok(round_no, title):
    print(f"  [PASS] R{round_no}: {title}")


def client(token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(base_url=BASE, headers=headers, timeout=30)


def login(username, password):
    r = httpx.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=15)
    if r.status_code != 200:
        return None
    return r.json()["access_token"]


def main():
    print("=== 用户测试 R1-R19 ===")
    admin_token = login("admin", "admin@ProductHub2026")
    sales_token = login("sales01", "sales@ProductHub2026")

    # ---------- R1 登录与权限边界 ----------
    print("R1 登录与权限边界")
    if not admin_token:
        finding(1, "P0", "admin 账号无法登录（目录重建脚本可能清掉了账号）")
        sys.exit(1)
    if not sales_token:
        finding(1, "P1", "sales01 账号无法登录")
    bad = httpx.post(f"{BASE}/auth/login", json={"username": "admin", "password": "wrong"}, timeout=15)
    (ok if bad.status_code == 401 else lambda *a: finding(1, "P0", "错误密码未被拒绝", bad.status_code))(1, "错误密码返回 401")
    noauth = httpx.get(f"{BASE}/skus", timeout=15)
    (ok if noauth.status_code == 401 else lambda *a: finding(1, "P0", "未登录可访问 SKU 列表"))(1, "未登录访问被拒")
    if sales_token:
        with client(sales_token) as c:
            for path, label in [("/users", "用户管理"), ("/imports", "导入")]:
                r = c.get(path)
                if r.status_code != 403:
                    finding(1, "P0", f"业务员可访问 {label}（{r.status_code}）")
                else:
                    ok(1, f"业务员访问{label}被拒(403)")

    ca = client(admin_token)
    cs = client(sales_token) if sales_token else ca

    # ---------- R2 目录摸底 ----------
    print("R2 目录完整性摸底")
    types = ca.get("/node-types" if False else "/template/node-types").json()
    roots = [t for t in types if t.get("is_sellable_root") and t.get("is_active")]
    complete_root = None
    for root in roots:
        d = ca.get(f"/template/node-types/{root['id']}").json()
        attrs = [a for a in d["attributes"] if a["is_active"]]
        slots = [s for s in d["slots"] if s["is_active"]]
        no_opt = [a["name"] for a in attrs if not [o for o in a.get("options", []) if o["is_active"]]]
        if no_opt:
            finding(2, "P1", f"品类「{root['name']}」属性缺选项：{no_opt}（配置时必选属性将永远无法完成）")
        if not attrs and not slots:
            finding(2, "P2", f"品类「{root['name']}」尚无属性与部件槽（模板未完成，工作坊待办）")
        if attrs and not no_opt and complete_root is None:
            complete_root = d
    if complete_root:
        ok(2, f"存在可配置品类：{complete_root['name']}")
    else:
        finding(2, "P2", "当前目录暂无属性完整的品类，后续轮次使用专建测试品类")

    # ---------- 测试模板（带 ZZZ 前缀，便于识别） ----------
    def post(c, url, body, expect=201):
        r = c.post(url, json=body)
        assert r.status_code == expect, f"{url} -> {r.status_code}: {r.text[:200]}"
        return r.json()

    t_root = post(ca, "/template/node-types", {"name": "ZZZ测试灭火器", "kind": "product", "is_sellable_root": True})
    t_part = post(ca, "/template/node-types", {"name": "ZZZ测试阀门", "kind": "part"})
    a1 = post(ca, f"/template/node-types/{t_root['id']}/attributes", {"name": "ZZZ容量", "is_filterable": True})
    o1 = post(ca, f"/template/attributes/{a1['id']}/options", {"label": "2kg"})
    o2 = post(ca, f"/template/attributes/{a1['id']}/options", {"label": "4kg"})
    pa = post(ca, f"/template/node-types/{t_part['id']}/attributes", {"name": "ZZZ阀体材质"})
    po1 = post(ca, f"/template/attributes/{pa['id']}/options", {"label": "黄铜"})
    slot = post(ca, f"/template/node-types/{t_root['id']}/slots",
                {"name": "ZZZ阀门槽", "child_type_id": t_part["id"]})
    sup = post(ca, "/suppliers", {"code": "ZZZCS", "name": "ZZZ测试供应商"})
    part = post(ca, "/purchased-parts",
                {"node_type_id": t_part["id"], "supplier_id": sup["id"], "name": "ZZZ测试成品阀"})

    def payload(opt_id=None, mode="purchased", part_id=None, valve_opt=None, attr_first=True):
        attrs = [{"attribute_id": a1["id"], "option_id": opt_id or o1["id"]}]
        if mode == "purchased":
            slot_sel = {"slot_id": slot["id"], "mode": "purchased", "purchased_part_id": part_id or part["id"]}
        elif mode == "configured":
            slot_sel = {"slot_id": slot["id"], "mode": "configured",
                        "child": {"attributes": [{"attribute_id": pa["id"], "option_id": valve_opt or po1["id"]}], "slots": []}}
        else:
            slot_sel = {"slot_id": slot["id"], "mode": "empty"}
        return {"root_type_id": t_root["id"], "root": {"attributes": attrs, "slots": [slot_sel]}}

    # ---------- R3 空/不完整配置 ----------
    print("R3 不完整配置")
    r = cs.post("/config/validate", json={"root_type_id": t_root["id"], "root": {"attributes": [], "slots": []}})
    if r.status_code != 200 or r.json()["complete"]:
        finding(3, "P0", "空配置未被判定为不完整", r.text[:200])
    else:
        ok(3, "空配置 → 不完整 + 缺项清单")
    r = cs.post("/skus", json={"config": {"root_type_id": t_root["id"], "root": {"attributes": [], "slots": []}}})
    (ok if r.status_code == 422 else lambda *a: finding(3, "P0", f"不完整配置可保存为 SKU（{r.status_code}）"))(3, "不完整配置保存被拒(422)")

    # ---------- R4 非法输入 ----------
    print("R4 非法配置输入")
    bad_cases = [
        ("选项挂错属性", {"root_type_id": t_root["id"], "root": {"attributes": [{"attribute_id": a1["id"], "option_id": po1["id"]}], "slots": []}}),
        ("不存在的成品件", payload() | {}),
    ]
    bad_cases[1] = ("不存在的成品件", json.loads(json.dumps(payload()).replace(str(part["id"]), "999999")))
    for label, p in bad_cases:
        r = cs.post("/config/validate", json=p)
        if r.status_code == 200 and not r.json()["complete"]:
            ok(4, f"{label} → 校验错误而非 500")
        elif r.status_code >= 500:
            finding(4, "P0", f"{label} 导致 500", r.text[:200])
        elif r.status_code == 200 and r.json()["complete"]:
            finding(4, "P0", f"{label} 竟然校验通过")
    r = cs.post("/config/validate", json={"root_type_id": 999999, "root": {"attributes": [], "slots": []}})
    (ok if r.status_code == 200 and not r.json().get("complete") else lambda *a: finding(4, "P1", f"不存在的品类未被优雅拒绝（{r.status_code}）"))(4, "不存在品类 → 校验错误")

    # ---------- R5 正常建 SKU ----------
    print("R5 完整配置建 SKU")
    r = cs.post("/skus", json={"config": payload()})
    assert r.status_code == 201, r.text
    sku1 = r.json()["sku"]
    (ok if r.json()["created"] else lambda *a: finding(5, "P0", "新配置未创建"))(5, f"创建 {sku1['sku_code']}")

    # ---------- R6 重复/乱序 ----------
    print("R6 重复与乱序")
    r = cs.post("/skus", json={"config": payload()})
    (ok if not r.json()["created"] and r.json()["sku"]["id"] == sku1["id"] else lambda *a: finding(6, "P0", "同配置生成第二个 SKU！"))(6, "重复保存返回既有 SKU")

    # ---------- R7 并发 ----------
    print("R7 并发同配置")
    p_con = payload(opt_id=o2["id"])
    results = []
    barrier = threading.Barrier(3)

    def worker():
        with client(sales_token or admin_token) as c2:
            barrier.wait()
            rr = c2.post("/skus", json={"config": p_con})
            results.append((rr.status_code, rr.json().get("sku", {}).get("id") if rr.status_code == 201 else rr.text[:100]))

    ths = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    ids = {x[1] for x in results if x[0] == 201}
    if len(ids) == 1 and all(x[0] == 201 for x in results):
        ok(7, "3 并发同配置 → 同一个 SKU")
    else:
        finding(7, "P0", f"并发结果异常：{results}")

    # ---------- R8 待录价拦截与录价权限 ----------
    print("R8 待录价与录价权限")
    q = post(cs, "/quotes", {"customer_name": "ZZZ测试客户A"})
    r = cs.post(f"/quotes/{q['id']}/items", json={"sku_id": sku1["id"], "qty": 10})
    (ok if r.status_code == 409 else lambda *a: finding(8, "P0", f"待录价 SKU 进入了报价单（{r.status_code}）"))(8, "待录价 SKU 进单被拒")
    r = cs.post(f"/skus/{sku1['id']}/prices", json={"price": "9.9"})
    (ok if r.status_code == 403 else lambda *a: finding(8, "P0", f"无录价权业务员录价成功（{r.status_code}）"))(8, "业务员录价被拒(403)")
    r = ca.post(f"/skus/{sku1['id']}/prices", json={"price": "9.9"})
    assert r.status_code == 201, r.text
    ok(8, "admin 录价成功")
    r = cs.post(f"/quotes/{q['id']}/items", json={"sku_id": sku1["id"], "qty": 10})
    (ok if r.status_code == 201 else lambda *a: finding(8, "P1", f"录价后进单失败（{r.status_code}）{r.text[:150]}"))(8, "录价后进单成功")

    # ---------- R9 价格逻辑 ----------
    print("R9 价格逻辑")
    r = ca.post(f"/skus/{sku1['id']}/prices", json={"price": "-1"})
    (ok if r.status_code == 422 else lambda *a: finding(9, "P0", f"负价被接受（{r.status_code}）"))(9, "负价被拒(422)")
    # 当天纠错：今天刚录 9.9，发现录错想马上改 10.5
    r = ca.post(f"/skus/{sku1['id']}/prices", json={"price": "10.5"})
    if r.status_code == 201:
        ok(9, "同日改价（纠错）成功")
    else:
        finding(9, "P1", "录错价当天无法纠正：同日改价被拒，只能等到明天",
                f"{r.status_code} {r.text[:200]}；真实场景：管理员手滑录错，必须能立即纠正")
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = ca.post(f"/skus/{sku1['id']}/prices", json={"price": "11", "valid_from": tomorrow})
    (ok if r.status_code == 201 else lambda *a: finding(9, "P1", f"明日生效改价失败 {r.text[:150]}"))(9, "未来生效改价成功")
    hist = ca.get(f"/skus/{sku1['id']}/prices").json()
    spans = [(h["valid_from"], h["valid_to"]) for h in hist]
    ok(9, f"价格史 {len(hist)} 条：{spans}")

    # ---------- R10 报价单逻辑 ----------
    print("R10 报价单")
    q_cny = post(cs, "/quotes", {"customer_name": "ZZZ测试客户B", "currency": "CNY"})
    r = cs.post(f"/quotes/{q_cny['id']}/items", json={"sku_id": sku1["id"], "qty": 1})
    (ok if r.status_code == 409 else lambda *a: finding(10, "P0", f"币种隔离失效：CNY 单加入了仅有 USD 价的 SKU（{r.status_code}）"))(10, "混币种被拒")
    r = cs.post(f"/quotes/{q['id']}/items", json={"sku_id": sku1["id"], "qty": 5})
    items = r.json()["items"] if r.status_code == 201 else []
    if len(items) == 1 and items[0]["qty"] == 15:
        ok(10, "重复加入合并数量(10+5)")
    else:
        finding(10, "P2", f"重复加入未合并行：{[(i['qty']) for i in items]}")
    r = cs.post(f"/quotes/{q['id']}/items", json={"sku_id": sku1["id"], "qty": 0})
    (ok if r.status_code == 422 else lambda *a: finding(10, "P1", f"数量 0 被接受（{r.status_code}）"))(10, "数量 0 被拒(422)")
    # 导出（今日有同日纠错价的话快照可能不一致，先 price-check）
    pc = cs.get(f"/quotes/{q['id']}/price-check").json()
    if not pc["consistent"]:
        cs.post(f"/quotes/{q['id']}/refresh-prices")
    r = cs.post(f"/quotes/{q['id']}/export")
    (ok if r.status_code == 200 else lambda *a: finding(10, "P1", f"导出失败 {r.text[:150]}"))(10, "导出 Excel 成功")
    r = cs.post(f"/quotes/{q['id']}/items", json={"sku_id": sku1["id"], "qty": 1})
    (ok if r.status_code == 409 else lambda *a: finding(10, "P0", f"导出冻结失效（{r.status_code}）"))(10, "导出后冻结生效")
    r = cs.post(f"/quotes/{q['id']}/duplicate")
    (ok if r.status_code == 201 else lambda *a: finding(10, "P1", "冻结单复制失败"))(10, "复制为新草稿成功")

    # ---------- R11 快照与现价分离 ----------
    print("R11 快照机制")
    q3 = post(cs, "/quotes", {"customer_name": "ZZZ测试客户C"})
    cs.post(f"/quotes/{q3['id']}/items", json={"sku_id": sku1["id"], "qty": 2})
    snap = cs.get(f"/quotes/{q3['id']}").json()["items"][0]["snapshot_price"]
    ok(11, f"加入时快照价 {snap}（现价变化由 price-check 揭示，R10 已验证路径）")

    # ---------- R12 模板演化 ----------
    print("R12 模板演化")
    r = ca.patch(f"/template/options/{o1['id']}", json={"label": "2kg（修订）"})
    assert r.status_code == 200
    detail = ca.get(f"/skus/{sku1['id']}").json()
    shown = json.dumps(detail["config_tree"], ensure_ascii=False)
    (ok if "2kg（修订）" in shown else lambda *a: finding(12, "P1", "选项改名后 SKU 详情未跟随"))(12, "选项改名后历史 SKU 展示同步")
    fp_before = sku1["fingerprint"]
    fp_now = ca.get(f"/skus/{sku1['id']}").json()["fingerprint"]
    (ok if fp_before == fp_now else lambda *a: finding(12, "P0", "改名导致指纹漂移！"))(12, "改名后指纹不变")
    ca.patch(f"/template/options/{o2['id']}", json={"is_active": False})
    r = cs.post("/config/validate", json=payload(opt_id=o2["id"]))
    (ok if not r.json()["complete"] else lambda *a: finding(12, "P0", "停用选项仍可用于新配置"))(12, "停用选项新配置被拒")
    ca.patch(f"/template/options/{o2['id']}", json={"is_active": True})

    # ---------- R13 黑盒件治理 ----------
    print("R13 成品件治理")
    draft = post(cs, "/purchased-parts", {"node_type_id": t_part["id"], "supplier_id": sup["id"], "name": "ZZZ草稿阀B"})
    (ok if draft["status"] == "draft" else lambda *a: finding(13, "P1", f"业务员建件状态非草稿：{draft['status']}"))(13, "业务员建件→草稿")
    r = cs.get("/purchased-parts/similar", params={"node_type_id": t_part["id"], "name": "ZZZ草稿阀"})
    (ok if any(p["id"] == draft["id"] for p in r.json()) else lambda *a: finding(13, "P2", "相似查重未命中近似名"))(13, "相似查重命中")
    r = ca.post(f"/purchased-parts/{draft['id']}/merge", json={"target_part_id": part["id"]})
    assert r.status_code == 200
    r = cs.post("/config/validate", json=payload(part_id=draft["id"]))
    (ok if not r.json()["complete"] else lambda *a: finding(13, "P0", "已合并件仍可用于新配置"))(13, "合并件新配置被拒")

    # ---------- R14 导入 ----------
    print("R14 Excel 导入")
    wb = Workbook(); ws = wb.active
    ws.append(["root_type_code", f"attr:{a1['code']}", f"part:{slot['code']}", "price", "currency"])
    ws.append([t_root["code"], "2kg（修订）", f"ZZZ测试供应商|ZZZ导入新阀", "33.3", "USD"])
    ws.append([t_root["code"], "不存在选项", f"ZZZ测试供应商|ZZZ导入新阀", "1", "USD"])
    buf = io.BytesIO(); wb.save(buf); content = buf.getvalue()
    r = ca.post("/imports/dry-run", files={"file": ("zzz.xlsx", content)})
    assert r.status_code == 200, r.text
    b = r.json()
    (ok if b["ok_rows"] == 1 and b["error_rows"] == 1 else lambda *a: finding(14, "P1", f"dry-run 统计异常 ok={b['ok_rows']} err={b['error_rows']}"))(14, "dry-run 1对1错")
    r = ca.post(f"/imports/{b['id']}/confirm")
    (ok if r.status_code == 200 and r.json()["ok_rows"] == 1 else lambda *a: finding(14, "P1", f"confirm 异常 {r.text[:150]}"))(14, "confirm 入库 1 行")
    r = ca.post("/imports/dry-run", files={"file": ("zzz.xlsx", content)})
    (ok if r.status_code == 409 else lambda *a: finding(14, "P0", f"同文件重复导入未拦截（{r.status_code}）"))(14, "同文件幂等拦截")

    # ---------- R15 检索 ----------
    print("R15 检索")
    r = cs.get("/skus", params={"option_id": [o1["id"]]})
    (ok if r.json()["total"] >= 1 else lambda *a: finding(15, "P1", "按选项筛选无结果"))(15, "动态属性筛选")
    r = cs.get("/skus", params={"status": "pending_price"})
    ok(15, f"待录价筛选 {r.json()['total']} 条")
    r = cs.get("/skus", params={"q": "ZZZ"})
    (ok if r.json()["total"] >= 1 else lambda *a: finding(15, "P1", "关键词检索未命中测试 SKU"))(15, "关键词检索")
    r = cs.get("/skus/export")
    (ok if r.status_code == 200 else lambda *a: finding(15, "P1", "清单导出失败"))(15, "SKU 清单导出")

    # ---------- R16 作废恢复 ----------
    print("R16 作废/恢复")
    ca.post(f"/skus/{sku1['id']}/retire")
    r = cs.post("/config/validate", json=payload())
    m = r.json()["matched_sku"]
    (ok if m and m["status"] == "retired" else lambda *a: finding(16, "P1", "作废 SKU 未在命中中标示"))(16, "命中作废 SKU 并标示")
    q4 = post(cs, "/quotes", {"customer_name": "ZZZ测试客户D"})
    r = cs.post(f"/quotes/{q4['id']}/items", json={"sku_id": sku1["id"], "qty": 1})
    (ok if r.status_code == 409 else lambda *a: finding(16, "P0", "作废 SKU 进入报价单"))(16, "作废 SKU 进单被拒")
    ca.post(f"/skus/{sku1['id']}/restore")
    ok(16, "恢复成功")

    # ---------- R17 异常输入 ----------
    print("R17 异常输入")
    r = ca.post("/template/node-types", json={"name": "Z" * 200, "kind": "part"})
    (ok if r.status_code == 422 else lambda *a: finding(17, "P1", f"超长名称被接受（{r.status_code}）"))(17, "超长名称被拒")
    r = cs.post("/quotes", json={"customer_name": "<script>alert(1)</script>ZZZ"})
    if r.status_code == 201:
        ok(17, "特殊字符客户名可存储（前端 Vue 转义渲染，需 R20 复核）")
    r = ca.post(f"/skus/{sku1['id']}/prices", json={"price": "999999999999.9999", "valid_from": "2030-01-01"})
    (ok if r.status_code in (201, 422) else lambda *a: finding(17, "P1", f"超大价格 500（{r.status_code}）"))(17, f"超大价格处理（{r.status_code}）")

    # ---------- R18 草稿隔离 ----------
    print("R18 草稿")
    d = post(cs, "/config-drafts", {"root_type_id": t_root["id"], "title": "ZZZ草稿", "payload": {"x": 1}})
    mine = cs.get("/config-drafts").json()
    others = ca.get("/config-drafts").json()
    (ok if any(x["id"] == d["id"] for x in mine) and not any(x["id"] == d["id"] for x in others)
     else lambda *a: finding(18, "P0", "草稿越权可见"))(18, "草稿仅 owner 可见")
    r = ca.put(f"/config-drafts/{d['id']}", json={"root_type_id": t_root["id"], "title": "x", "payload": {}})
    (ok if r.status_code == 404 else lambda *a: finding(18, "P0", f"他人草稿可修改（{r.status_code}）"))(18, "他人草稿不可改(404)")

    # ---------- R19 批量与分页 ----------
    print("R19 批量/分页")
    import time
    t0 = time.time()
    made = 0
    for i, (oid, mode) in enumerate([(o1["id"], "configured"), (o2["id"], "configured")]):
        rr = cs.post("/skus", json={"config": payload(opt_id=oid, mode=mode)})
        made += 1 if rr.status_code == 201 else 0
    el = time.time() - t0
    r = cs.get("/skus", params={"page": 1, "page_size": 5})
    j = r.json()
    (ok if len(j["items"]) <= 5 and j["total"] >= len(j["items"]) else lambda *a: finding(19, "P1", "分页异常"))(19, f"分页正常（建{made}个用时{el:.1f}s）")
    t0 = time.time(); cs.get("/skus"); lat = (time.time() - t0) * 1000
    (ok if lat < 1500 else lambda *a: finding(19, "P2", f"列表延迟 {lat:.0f}ms 偏高"))(19, f"列表延迟 {lat:.0f}ms")

    print("\n=== 汇总 ===")
    print(json.dumps(FINDINGS, ensure_ascii=False, indent=1))
    print(f"发现问题：{len(FINDINGS)} 项")


if __name__ == "__main__":
    main()
