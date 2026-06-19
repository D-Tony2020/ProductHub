"""SKU：创建（配置落库）、检索（动态属性筛选）、详情（只读配置树+价格史）、作废/恢复、清单导出。"""
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, selectinload

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import (
    AppUser,
    AttributeDef,
    NodeType,
    PurchasedPart,
    Sku,
    SkuAttributeValue,
    SkuConfigNode,
    SkuPrice,
)
from app.schemas.config import CurrentPrice
from app.schemas.sku import (
    SkuAttributeValueOut,
    SkuCreateIn,
    SkuCreateResult,
    SkuDetailOut,
    SkuHealth,
    SkuListOut,
    SkuNodeOut,
    SkuOut,
    SkuOverviewOut,
    SkuStatsOut,
    SkuUpdateIn,
    SkuUpdateResult,
)
from app.services.config_engine import _current_prices, create_sku, current_prices_batch
from app.services.graybox import summarize_spec
from app.services.health_engine import compute_health, load_sku_for_health
from app.services.template_service import get_or_404

router = APIRouter(prefix="/skus", tags=["skus"])

_EXPORT_CAP = 50000  # 导出行数上限：防海量下 openpyxl 全本驻内存爆内存；超限截断并在表尾标注

# 现价存在性谓词（相关 EXISTS，走 ix_sku_price_current 部分索引；取代对视图的 IN/NOT IN 反连接，
# 避免大表整表物化 sku_id 集合与 NOT IN 的 NULL 反连接代价）。引用外层 sku.id，FROM 须为未起别名的 sku。
_HAS_CURRENT_PRICE = "EXISTS (SELECT 1 FROM v_sku_current_price cp WHERE cp.sku_id = sku.id)"
_NO_CURRENT_PRICE = f"NOT {_HAS_CURRENT_PRICE}"

# 健康的集合下推判定：替代"逐 SKU 跑 compute_health"的 O(n) 全表遍历(海量会超时)。
# 拆成两族，与 compute_health 的 family 对齐，以支撑列表三态徽标 + 报价闸口径一致：
#   · 供给族 _SUPPLY_SKU(黄·supply_warn·不阻断报价)：配置引用了停用/不可用的模板要素——
#       ① 停用节点类型 ② 不可用成品件(非 draft/active) ③ 停用供应商 ④ 停用选项
#   · 完整性族 _BLOCKING_SKU(红·incomplete·阻断报价)：缺"现已必选"的属性/必配非互斥槽——
#       ⑤ 缺必选属性  ⑥ 缺必配·非互斥部件槽(模板事后收紧的漂移)
# 待治理 = 两族之并(=非 ok)；stats/overview 计数用 _NONOK_SKU。仅"互斥组(variant_group)
# 结构违规"(0选/多选·极罕见)不在此快速口径内；单 SKU 权威健康仍以 compute_health 为准。
# 三处子句均引用外层 sku.id 作 WHERE 谓词嵌入(FROM 表须为未起别名的 sku)。
_SUPPLY_SKU = """(
  EXISTS (SELECT 1 FROM sku_config_node cn JOIN node_type nt ON nt.id = cn.node_type_id
          WHERE cn.sku_id = sku.id AND nt.is_active = false)
  OR EXISTS (SELECT 1 FROM sku_config_node cn JOIN purchased_part pp ON pp.id = cn.purchased_part_id
             WHERE cn.sku_id = sku.id AND pp.status NOT IN ('draft', 'active'))
  OR EXISTS (SELECT 1 FROM sku_config_node cn JOIN supplier su ON su.id = cn.supplier_id
             WHERE cn.sku_id = sku.id AND su.is_active = false)
  OR EXISTS (SELECT 1 FROM sku_config_node cn JOIN sku_attribute_value av ON av.config_node_id = cn.id
             JOIN attribute_option ao ON ao.id = av.option_id
             WHERE cn.sku_id = sku.id AND ao.is_active = false)
)"""
_BLOCKING_SKU = """(
  EXISTS (SELECT 1 FROM sku_config_node cn
          JOIN attribute_def ad ON ad.node_type_id = cn.node_type_id
               AND ad.is_active AND ad.is_required
          WHERE cn.sku_id = sku.id AND cn.mode = 'configured'
            AND NOT EXISTS (SELECT 1 FROM sku_attribute_value av
                            WHERE av.config_node_id = cn.id AND av.attribute_id = ad.id))
  OR EXISTS (SELECT 1 FROM sku_config_node cn
             JOIN component_slot cs ON cs.parent_type_id = cn.node_type_id
                  AND cs.is_active AND cs.is_required AND cs.variant_group IS NULL
             WHERE cn.sku_id = sku.id AND cn.mode = 'configured'
               AND NOT EXISTS (SELECT 1 FROM sku_config_node ch
                               WHERE ch.parent_node_id = cn.id AND ch.slot_id = cs.id))
)"""
# 待治理 = 完整性族 ∪ 供给族（非 ok）。stats/overview/incomplete 筛选计数用。
_NONOK_SKU = f"({_BLOCKING_SKU} OR {_SUPPLY_SKU})"

# 采购来源分面谓词（相关 EXISTS，引用未起别名的 sku）。三类在数据上近似互斥且全覆盖：
#   · blackbox 含外购子件：配置树存在挂在子节点上的外购成品件（最典型的贸易拼装）
#   · whitebox 纯自配：全树无任何外购件（完全自行配置）
#   · direct   整机直采：根节点本身即一件外购成品（按成品整机直接采购转售）
# 全部为服务端常量，不接受任何用户字符串拼接（facet 键经白名单校验后才取用）。
_SOURCING_SQL = {
    "blackbox": "EXISTS (SELECT 1 FROM sku_config_node cn WHERE cn.sku_id = sku.id "
                "AND cn.purchased_part_id IS NOT NULL AND cn.parent_node_id IS NOT NULL)",
    "whitebox": "NOT EXISTS (SELECT 1 FROM sku_config_node cn WHERE cn.sku_id = sku.id "
                "AND cn.purchased_part_id IS NOT NULL)",
    "direct": "EXISTS (SELECT 1 FROM sku_config_node cn WHERE cn.sku_id = sku.id "
              "AND cn.purchased_part_id IS NOT NULL AND cn.parent_node_id IS NULL)",
}


def _health_status_map(db: Session, sku_ids: list[int]) -> dict[int, str]:
    """一次性判定一页 SKU 的健康徽标(集合下推)，替代逐行 compute_health。
    返回 {sku_id: 'incomplete'|'supply_warn'}，未列入者即 'ok'。阻断优先于供给(与 compute_health 一致)。"""
    if not sku_ids:
        return {}
    blocking = set(db.execute(
        sql_text(f"SELECT sku.id FROM sku WHERE sku.id = ANY(:ids) AND {_BLOCKING_SKU}"),
        {"ids": sku_ids}).scalars())
    supply = set(db.execute(
        sql_text(f"SELECT sku.id FROM sku WHERE sku.id = ANY(:ids) AND {_SUPPLY_SKU}"),
        {"ids": sku_ids}).scalars())
    return {sid: ("incomplete" if sid in blocking else "supply_warn")
            for sid in (blocking | supply)}


# 批量现价：复用 config_engine.current_prices_batch（与 _current_prices 同口径，单一真源）
_current_prices_map = current_prices_batch


def _sku_out(
    db: Session, sku: Sku, health_status: str | None = None,
    prices: list[CurrentPrice] | None = None,
) -> SkuOut:
    out = SkuOut.model_validate(sku, from_attributes=True)
    out.root_type_name = sku.root_type.name if sku.root_type else ""
    # 批量场景由调用方预取现价传入(消 N+1)；单条场景回落到逐 SKU 查
    out.current_prices = prices if prices is not None else _current_prices(db, sku.id)
    out.health_status = health_status  # 由调用方实时推导填入（列表/详情）
    if sku.superseded_by_sku_id and sku.superseded_by:
        out.superseded_by_sku_code = sku.superseded_by.sku_code  # 血缘展示
    return out


def _node_out(db: Session, node: SkuConfigNode, node_types: dict[int, NodeType]) -> SkuNodeOut:
    attrs = []
    for av in sorted(node.attribute_values, key=lambda v: v.attribute.display_order):
        attrs.append(
            SkuAttributeValueOut(
                attribute_id=av.attribute_id,
                option_id=av.option_id,
                attribute_code=av.attribute.code,
                attribute_name=av.attribute.name,
                option_code=av.option.code,
                option_label=av.option.label,
                option_active=av.option.is_active,
            )
        )
    part = node.purchased_part
    # 来源：黑盒由成品件供应商派生；白盒由节点级供应商标注（方案甲）
    if part is not None:
        supplier_id, supplier_name = part.supplier_id, part.supplier.name
    elif node.supplier_id is not None:
        supplier_id, supplier_name = node.supplier_id, node.supplier.name if node.supplier else None
    else:
        supplier_id, supplier_name = None, None
    return SkuNodeOut(
        id=node.id,
        slot_id=node.slot_id,
        slot_code=node.slot.code if node.slot else None,
        slot_name=node.slot.name if node.slot else None,
        node_type_id=node.node_type_id,
        node_type_code=node_types[node.node_type_id].code,
        node_type_name=node_types[node.node_type_id].name,
        mode=node.mode,
        purchased_part_id=part.id if part else None,
        purchased_part_name=part.name if part else None,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        part_spec_note=part.spec_note if part else None,
        part_spec_summary=summarize_spec(db, part.spec_config) if part else "",
        attributes=attrs,
        children=[
            _node_out(db, c, node_types)
            for c in sorted(node.children, key=lambda c: (c.slot.display_order if c.slot else 0))
        ],
    )


@router.post("", response_model=SkuCreateResult, status_code=201)
def create(
    body: SkuCreateIn,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    sku, created = create_sku(db, body.config, created_by=user.id)
    if created:
        write_audit(db, actor_id=user.id, action="create", entity_type="sku",
                    entity_id=sku.id, after={"sku_code": sku.sku_code,
                                             "fingerprint": sku.fingerprint})
    db.commit()
    return SkuCreateResult(created=created, sku=_sku_out(db, sku))


@router.get("", response_model=SkuListOut)
def search(
    q: str | None = Query(default=None, max_length=200),
    root_type_id: int | None = None,
    status: str | None = Query(default=None, pattern=r"^(active|retired|pending_price|incomplete)$"),
    option_id: list[int] = Query(default=[]),
    purchased_part_id: int | None = None,
    supplier_id: int | None = None,
    supplier_part_type_id: int | None = None,
    sp_pair: list[str] = Query(default=[]),  # 结构化检索·多对"供应商id:件类型id"，各自 AND
    sort: str = Query(default="recent",
                      pattern=r"^(recent|price_asc|price_desc|created_asc|code|name)$"),
    currency: str = Query(default="USD", pattern=r"^[A-Z]{3}$"),
    price_min: Decimal | None = Query(default=None, ge=0),
    price_max: Decimal | None = Query(default=None, ge=0),
    quotable: bool = False,
    sourcing: list[str] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    mine: bool = False,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    stmt = select(Sku)
    if mine:
        stmt = stmt.where(Sku.created_by == user.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Sku.sku_code.ilike(like) | Sku.name.ilike(like))
    if root_type_id is not None:
        stmt = stmt.where(Sku.root_type_id == root_type_id)
    if status == "pending_price":
        # 待录价 = active 且无现行价（推导态，无冗余状态字段）；NOT EXISTS 相关子查询走索引
        stmt = stmt.where(Sku.status == "active", sql_text(_NO_CURRENT_PRICE))
    elif status == "incomplete":
        # 残货 = active 且引用停用要素/缺必选属性，集合下推（见 _NONOK_SKU），与统计带口径一致
        stmt = stmt.where(Sku.status == "active", sql_text(_NONOK_SKU))
    elif status is not None:
        stmt = stmt.where(Sku.status == status)
    for oid in option_id:
        # 每个选中的选项都要求 SKU 配置树中存在该取值（跨节点 AND 语义）
        stmt = stmt.where(
            Sku.id.in_(
                select(SkuConfigNode.sku_id)
                .join(SkuAttributeValue, SkuAttributeValue.config_node_id == SkuConfigNode.id)
                .where(SkuAttributeValue.option_id == oid)
            )
        )
    if purchased_part_id is not None:
        stmt = stmt.where(
            Sku.id.in_(
                select(SkuConfigNode.sku_id).where(
                    SkuConfigNode.purchased_part_id == purchased_part_id
                )
            )
        )
    if supplier_id is not None:
        # 关联成品口径（与供应商概览 linked_skus / 关联成品页 /suppliers/{id}/linked-skus 同口径）：
        # 黑盒 ∪ 白盒，"出现即计入"。
        #   · 黑盒：配置树某节点的外购成品件来自该供应商（scn.purchased_part_id → pp.supplier_id）
        #   · 白盒：配置树某节点直接标注该供应商（scn.supplier_id，方案甲采购溯源）
        # 纯自产且无任何来源标注的 SKU 天然不落入任何供应商，符合设计。
        black = (
            select(SkuConfigNode.sku_id)
            .join(PurchasedPart, PurchasedPart.id == SkuConfigNode.purchased_part_id)
            .where(PurchasedPart.supplier_id == supplier_id)
        )
        white = select(SkuConfigNode.sku_id).where(SkuConfigNode.supplier_id == supplier_id)
        # 「供应商×件类型」下钻：再收窄到"该命中节点本身是该件类型"，与 category-breakdown 同口径
        # （count == 本筛选 total，数字对齐）。仅在 supplier_id 给定时生效。
        if supplier_part_type_id is not None:
            black = black.where(SkuConfigNode.node_type_id == supplier_part_type_id)
            white = white.where(SkuConfigNode.node_type_id == supplier_part_type_id)
        stmt = stmt.where(Sku.id.in_(black) | Sku.id.in_(white))
    # 结构化检索·多对来源约束：每个"供应商id:件类型id"对各自 AND（黑∪白），
    # 与 option_id 的逐条目子查询叠加同构——表达"该部件由该供应商供应"，可任意多对并立。
    for pair in sp_pair:
        sid_ntid = pair.split(":", 1)
        if len(sid_ntid) != 2 or not all(x.lstrip("-").isdigit() for x in sid_ntid):
            continue  # 形如 "3:24"；非法静默跳过（防注入：只接受两个整数）
        sid, ntid = int(sid_ntid[0]), int(sid_ntid[1])
        pblack = (
            select(SkuConfigNode.sku_id)
            .join(PurchasedPart, PurchasedPart.id == SkuConfigNode.purchased_part_id)
            .where(PurchasedPart.supplier_id == sid, SkuConfigNode.node_type_id == ntid)
        )
        pwhite = select(SkuConfigNode.sku_id).where(
            SkuConfigNode.supplier_id == sid, SkuConfigNode.node_type_id == ntid)
        stmt = stmt.where(Sku.id.in_(pblack) | Sku.id.in_(pwhite))
    # 采购来源分面（分面内 OR：选中多类取并集）。键经 _SOURCING_SQL 白名单过滤，只拼服务端常量
    sourcing_clauses = [_SOURCING_SQL[k] for k in dict.fromkeys(sourcing) if k in _SOURCING_SQL]
    if sourcing_clauses:
        stmt = stmt.where(sql_text("(" + " OR ".join(sourcing_clauses) + ")"))
    # 现价价格区间（逐币种）：仅当该币种存在落在区间内的现价才命中。:ccy/:pmin/:pmax 绑定防注入，
    # 走 v_sku_current_price（已收口 superseded/有效期）+ ix_sku_price_current 部分索引
    price_conds = []
    if price_min is not None:
        price_conds.append("cp.price >= :pmin")
    if price_max is not None:
        price_conds.append("cp.price <= :pmax")
    if price_conds:
        params: dict = {"ccy": currency}
        if price_min is not None:
            params["pmin"] = price_min
        if price_max is not None:
            params["pmax"] = price_max
        stmt = stmt.where(sql_text(
            "EXISTS (SELECT 1 FROM v_sku_current_price cp "
            "WHERE cp.sku_id = sku.id AND cp.currency = :ccy AND "
            + " AND ".join(price_conds) + ")"
        ).bindparams(**params))
    if quotable:
        # 可立即报价 = active ∧ 不缺必选(不触报价闸) ∧ 该币种有现价（与 quotes.add 三道闸同口径）
        stmt = stmt.where(
            Sku.status == "active",
            sql_text(f"NOT {_BLOCKING_SKU}"),
            sql_text("EXISTS (SELECT 1 FROM v_sku_current_price cp "
                     "WHERE cp.sku_id = sku.id AND cp.currency = :ccy)").bindparams(ccy=currency),
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    # 排序：价格档走逐币种现价相关子查询（NULLS LAST 把无价沉底，再以 id 兜稳定序）；
    # 其余档走 sku 本表列（id/sku_code/name/created_at 均有索引）。direction 取自定值集，非用户串。
    if sort in ("price_asc", "price_desc"):
        direction = "ASC" if sort == "price_asc" else "DESC"
        order_by: tuple = (
            sql_text(
                "(SELECT cp.price FROM v_sku_current_price cp "
                f"WHERE cp.sku_id = sku.id AND cp.currency = :ccy LIMIT 1) {direction} NULLS LAST"
            ).bindparams(ccy=currency),
            Sku.id.desc(),
        )
    elif sort == "created_asc":
        order_by = (Sku.id.asc(),)
    elif sort == "code":
        order_by = (Sku.sku_code.asc(),)
    elif sort == "name":
        order_by = (Sku.name.asc(), Sku.id.desc())
    else:  # recent（综合·最新）：与历史默认一致
        order_by = (Sku.id.desc(),)

    # 列表徽标改集合下推(不再逐行 compute_health 遍历配置树)，现价改批量 IN(不再逐 SKU N+1)，
    # 仅预取 root_type / superseded_by(展示用)——一页固定几条 SQL，与本页行数无关。
    rows = db.execute(
        stmt.options(selectinload(Sku.root_type), selectinload(Sku.superseded_by))
        .order_by(*order_by).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    page_ids = [s.id for s in rows]
    health = _health_status_map(db, page_ids)
    prices = _current_prices_map(db, page_ids)
    return SkuListOut(
        total=total,
        items=[_sku_out(db, s, health.get(s.id, "ok"), prices.get(s.id, [])) for s in rows],
    )


@router.get("/stats", response_model=SkuStatsOut)
def stats(db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """SKU 库统计带：货架口径四个数。须声明在 /skus/{sku_id} 之前以免被动态路由捕获。"""
    active = db.execute(
        select(func.count()).select_from(Sku)
        .where(Sku.status == "active", sql_text(_HAS_CURRENT_PRICE))
    ).scalar_one()
    pending = db.execute(
        select(func.count()).select_from(Sku)
        .where(Sku.status == "active", sql_text(_NO_CURRENT_PRICE))
    ).scalar_one()
    new_week = db.execute(
        select(func.count()).select_from(Sku)
        .where(Sku.status == "active", Sku.created_at >= datetime.now() - timedelta(days=7))
    ).scalar_one()
    today = date.today()
    # 在售且"当前生效价"的生效日已满 30 天：提醒管理者复审久未动价的货
    stale = db.execute(
        select(func.count(func.distinct(SkuPrice.sku_id)))
        .select_from(SkuPrice).join(Sku, Sku.id == SkuPrice.sku_id)
        .where(
            Sku.status == "active",
            SkuPrice.valid_from <= today - timedelta(days=30),
            (SkuPrice.valid_to.is_(None)) | (SkuPrice.valid_to >= today),
        )
    ).scalar_one()
    # 待治理（残货）：在售且引用停用要素/缺必选属性——集合下推，O(1) 查询而非逐 SKU 遍历
    incomplete = db.execute(
        select(func.count()).select_from(Sku)
        .where(Sku.status == "active", sql_text(_NONOK_SKU))
    ).scalar_one()
    return SkuStatsOut(active=active, pending_price=pending,
                       new_this_week=new_week, stale_30d=stale, incomplete=incomplete)


@router.get("/overview", response_model=list[SkuOverviewOut])
def overview(db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """产品全貌：按可售品类聚合（比 SKU 粗一档）。产品库首页"全貌"视图的数据源。"""
    # ① 每根一次 GROUP BY 聚合：sku_count / pending(无任何币种现价) / incomplete(残货·_NONOK_SKU 下推)
    #    彻底替代原"逐根 selectinload 全部在售 SKU 整树 + 逐 SKU compute_health/现价"的 O(n) 重聚合
    #    （即旧 /stats 12s 超时同款模式）。规模无关，常数条查询。
    count_rows = db.execute(sql_text(f"""
        SELECT sku.root_type_id AS rid,
               count(*) AS sku_count,
               count(*) FILTER (
                   WHERE NOT EXISTS (SELECT 1 FROM v_sku_current_price cp WHERE cp.sku_id = sku.id)
               ) AS pending,
               count(*) FILTER (WHERE {_NONOK_SKU}) AS incomplete
        FROM sku
        WHERE sku.status = 'active'
        GROUP BY sku.root_type_id
    """)).all()
    counts = {r.rid: r for r in count_rows}
    # ② 每根×币种聚合现价 min/max；取条目最多的币种为代表（避免跨币种混算 min/max 的旧问题）
    price_rows = db.execute(sql_text("""
        SELECT sku.root_type_id AS rid, cp.currency AS currency,
               min(cp.price) AS pmin, max(cp.price) AS pmax, count(*) AS n
        FROM sku JOIN v_sku_current_price cp ON cp.sku_id = sku.id
        WHERE sku.status = 'active'
        GROUP BY sku.root_type_id, cp.currency
    """)).all()
    price_by_root: dict = {}
    for r in price_rows:
        cur = price_by_root.get(r.rid)
        if cur is None or r.n > cur["n"]:
            price_by_root[r.rid] = {"currency": r.currency, "pmin": r.pmin, "pmax": r.pmax, "n": r.n}
    # ③ 列出全部可售根（含 0 SKU 的），带槽/属性计数
    roots = db.execute(
        select(NodeType).where(NodeType.is_sellable_root.is_(True))
        .options(selectinload(NodeType.slots), selectinload(NodeType.attributes))
        .order_by(NodeType.display_order, NodeType.id)
    ).scalars().all()
    out: list[SkuOverviewOut] = []
    for rt in roots:
        c = counts.get(rt.id)
        p = price_by_root.get(rt.id)
        out.append(SkuOverviewOut(
            root_type_id=rt.id, root_type_name=rt.name, kind=rt.kind,
            sku_count=c.sku_count if c else 0,
            incomplete=c.incomplete if c else 0,
            pending_price=c.pending if c else 0,
            price_min=p["pmin"] if p else None,
            price_max=p["pmax"] if p else None,
            currency=p["currency"] if p else None,
            slot_count=len([x for x in rt.slots if x.is_active]),
            attr_count=len([a for a in rt.attributes if a.is_active]),
        ))
    return out


@router.get("/export")
def export_list(
    root_type_id: int | None = None,
    db: Session = Depends(get_db),
    _: AppUser = Depends(get_current_user),
):
    """SKU 清单导出 Excel（业务员高频）。批量取现价 + 预取品类(消 N+1)；行数封顶防内存爆。"""
    stmt = select(Sku).where(Sku.status == "active")
    if root_type_id is not None:
        stmt = stmt.where(Sku.root_type_id == root_type_id)
    # 封顶 + 1 探测是否超限；预取 root_type 避免逐行 lazy
    stmt = stmt.options(selectinload(Sku.root_type)).order_by(Sku.id).limit(_EXPORT_CAP + 1)
    skus = db.execute(stmt).scalars().all()
    truncated = len(skus) > _EXPORT_CAP
    skus = skus[:_EXPORT_CAP]
    prices_map = _current_prices_map(db, [s.id for s in skus])  # 一次批量 IN，替代逐 SKU N+1
    wb = Workbook()
    ws = wb.active
    ws.title = "SKU 清单"
    ws.append(["SKU 编码", "名称", "品类", "现价", "币种", "价格生效日", "状态"])
    for sku in skus:
        prices = prices_map.get(sku.id, [])
        p: CurrentPrice | None = prices[0] if prices else None
        ws.append([
            sku.sku_code, sku.name, sku.root_type.name if sku.root_type else "",
            float(p.price) if p else None, p.currency if p else "",
            p.valid_from if p else "", "在售" if prices else "待录价",
        ])
    if truncated:
        ws.append([])
        ws.append([f"⚠ 已截断：仅导出前 {_EXPORT_CAP} 条。请按品类/筛选缩小范围后再导出。"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"SKU-list-{datetime.now():%Y%m%d-%H%M}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{sku_id}", response_model=SkuDetailOut)
def detail(
    sku_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    sku = db.execute(
        select(Sku)
        .where(Sku.id == sku_id)
        .options(
            # 一次性预加载 _node_out 递归用到的全部关系，消除逐节点懒加载 N+1：
            # 属性值→属性/选项、采购件→供应商、槽、白盒节点供应商、子节点。
            selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values)
            .selectinload(SkuAttributeValue.attribute),
            selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values)
            .selectinload(SkuAttributeValue.option),
            selectinload(Sku.nodes).selectinload(SkuConfigNode.purchased_part)
            .selectinload(PurchasedPart.supplier),
            selectinload(Sku.nodes).selectinload(SkuConfigNode.slot),
            selectinload(Sku.nodes).selectinload(SkuConfigNode.supplier),
            selectinload(Sku.nodes).selectinload(SkuConfigNode.children),
        )
    ).scalar_one_or_none()
    if sku is None:
        raise HTTPException(404, f"SKU {sku_id} 不存在")
    # 件类型无 ORM 关系，一次性按主键批量取（~数十条），替代 _node_out 内逐节点 db.get。
    node_types = {nt.id: nt for nt in db.execute(select(NodeType)).scalars()}
    root = next((n for n in sku.nodes if n.parent_node_id is None), None)
    health = compute_health(db, sku)
    out = SkuDetailOut(
        **_sku_out(db, sku, health.status).model_dump(),
        config_tree=_node_out(db, root, node_types) if root else None,
        health=health,
    )
    return out


@router.get("/{sku_id}/health", response_model=SkuHealth)
def health(sku_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """SKU 在最新模板下的健康体检（三族）。实时推导、不碰指纹。"""
    sku = load_sku_for_health(db, sku_id)
    if sku is None:
        raise HTTPException(404, f"SKU {sku_id} 不存在")
    return compute_health(db, sku)


@router.post("/{sku_id}/retire", response_model=SkuOut)
def retire(
    sku_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)
):
    sku = get_or_404(db, Sku, sku_id)
    if sku.status == "retired":
        raise HTTPException(409, "SKU 已是作废状态")
    sku.status = "retired"
    write_audit(db, actor_id=user.id, action="retire", entity_type="sku",
                entity_id=sku.id, before={"status": "active"}, after={"status": "retired"})
    db.commit()
    return _sku_out(db, sku)


@router.post("/{sku_id}/restore", response_model=SkuOut)
def restore(
    sku_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)
):
    """作废恢复：同配置重配时引导恢复原 SKU 而非新建分身。"""
    sku = get_or_404(db, Sku, sku_id)
    if sku.status == "active":
        raise HTTPException(409, "SKU 已是在用状态")
    sku.status = "active"
    write_audit(db, actor_id=user.id, action="restore", entity_type="sku",
                entity_id=sku.id, before={"status": "retired"}, after={"status": "active"})
    db.commit()
    return _sku_out(db, sku)


@router.post("/{sku_id}/update", response_model=SkuUpdateResult, status_code=201)
def update_config(
    sku_id: int,
    body: SkuUpdateIn,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """修改既有 SKU 配置（M2-B 治理闭环）：绝不原地改（会变指纹），而是生成一个新 SKU、
    旧 SKU 留痕指向新 SKU，并按 retire_old 决定旧 SKU 停用还是保活（保活=仍可报价，只记血缘）。
    新配置不完整 → 422（沿用 create 同闸）；与原 SKU 完全相同 → 409（无修改）。"""
    old = get_or_404(db, Sku, sku_id)
    if old.status != "active" or old.superseded_at is not None:
        raise HTTPException(409, f"SKU {old.sku_code} 已作废或已被取代，不可再修改")
    new_sku, created = create_sku(db, body.config, created_by=user.id)
    if new_sku.id == old.id:
        # 指纹不变=没有实质修改，不产生血缘（杜绝自指与噪声）
        raise HTTPException(409, "新配置与原 SKU 完全相同，未发生任何修改")
    if not created and new_sku.status == "retired":
        # 改成了某个已作废配置 → 用户主动重新采纳，复活之（避免指向死链）
        new_sku.status = "active"
    old.superseded_by_sku_id = new_sku.id
    old.superseded_at = datetime.now()
    if body.retire_old:
        old.status = "retired"
    write_audit(
        db, actor_id=user.id, action="supersede", entity_type="sku", entity_id=old.id,
        before={"sku_code": old.sku_code, "status": "active"},
        after={"superseded_by": new_sku.sku_code, "new_sku_id": new_sku.id,
               "old_status": old.status, "created_new": created},
    )
    db.commit()
    return SkuUpdateResult(
        created=created,
        new_sku=_sku_out(db, new_sku, compute_health(db, new_sku).status),
        old_sku=_sku_out(db, old),
    )
