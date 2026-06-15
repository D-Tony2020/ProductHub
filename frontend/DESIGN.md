# ProductHub 前端设计系统 · DESIGN.md

> 「工业蓝 · 克制密度」——把原生默认 Element Plus 升级为一套内聚、有品牌感、双角色双密度、可暗色的 B2B 工业 SaaS 设计系统。**演进而非革命，零业务回归。**
>
> 本文是设计 + 研发的单一事实源（由前端部门多角色设计会产出，逐文件核对 + node_modules 源码核验）。

## 0. 核心原则（红线）

1. **不换组件库**：继续 Element Plus `^2.8.6`，所有页面 template/script/数据流/交互契约/路由/store 一行业务逻辑不动。
2. **令牌驱动换肤**：现代化 100% 通过「设计令牌（CSS 变量 + SCSS 主题覆盖）+ 外观精修 + 薄包装组件 + 工具类」实现。
3. **不增首屏**：`sass` 仅 devDependency（构建期）；`--ph-*` 是 `:root` 静态变量，无 JS 计算；字体系统优先、不强制下载。
4. **单一色彩源**：全站颜色只来自 `--ph-*` / `--el-*`，禁止裸 hex（现存 6 行硬编码须收编）。
5. **可切换设计**：密度（comfortable/compact）与暗色从第一天按可切换设计，所有色值经 `--ph-*` 中转。

技术地基（关键洞察）：全站颜色 **99% 已走 `--el-*` 变量**，硬编码仅 6 行（`Login.vue:57` 渐变 + `Suppliers.vue:281-285` 四张彩卡）。故建 `--ph-*` 真值层 → 重绑 `--el-*` → EP 组件与既有 scoped CSS 全自动继承换肤。

## 1. 落地结构（唯三结构改动）

```
frontend/src/styles/
  index.scss   ← 唯一主题入口
  tokens.scss  ← --ph-* 定义 + --el-* 重绑 + html.dark / html[data-density] 覆盖
  utils.scss   ← 工具类 + 全局 :deep(.el-table / .el-menu) 规则
```

```scss
/* index.scss —— @forward 必须在 @use EP 之前，才能编译期重算 primary-light-3..9 梯度 */
@forward 'element-plus/theme-chalk/src/common/var.scss' with (
  $colors: ('primary': ('base': #1f4e79)),
  $border-radius: ('base': 8px, 'small': 6px, 'round': 6px)
);
@use 'element-plus/theme-chalk/src/index.scss' as *;   // 替代 dist/index.css，使梯度生效
@use './tokens';
@use './utils';
```

- `main.ts:3`：`import 'element-plus/dist/index.css'` → `import './styles/index.scss'`。
- `package.json` devDependencies 加 `"sass": "^1.77.0"`（当前缺失，纯构建期、零运行时）。
- 收编 6 行 hex：`Login.vue:57`、`Suppliers.vue:281-285`（含 `color:#fff`，降级浅底后必须连前景色一起改）。

> ⚠ 为何必须走 SCSS 入口：EP 的 `primary-light-1..9` 由 `theme-chalk/src/common/var.scss:54-91` 在**编译期** `color.mix(#fff, base, n%)` 生成。运行时只改 `--el-color-primary` 不会重算梯度 → `.active` 选中浅底会与主色脱节撞色。

## 2. 设计令牌（`--ph-*`）

### 2.1 品牌色 · 工业蓝（沿用并提亮 Login 现有深蓝）
| 令牌 | 值 | 用途 |
|---|---|---|
| `--ph-brand-700` | `#16385a` | 按下 active |
| `--ph-brand-600` | `#1f4e79` | **主色**（→ `--el-color-primary` 经 SCSS 重算梯度）|
| `--ph-brand-500` | `#2c6aa0` | hover |

### 2.2 中性灰阶 · 9 级（Carbon + Geist 混合，比 EP 默认更冷、更有层次）
`gray-0 #ffffff` · `50 #f7f8fa` · `100 #eff1f4` · `200 #e4e7ec` · `300 #d0d5dd` · `400 #98a2b3` · `500 #667085` · `600 #475467` · `700 #344054` · `900 #101828`

职能：背景层 0/50/100；边框 200(subtle)/300/400(strong)；文本 500(placeholder)/600(secondary)/700(regular)/900(primary)。

### 2.3 语义色 · 成对（前景 + EP `-light-9` 浅底，不复用品牌色）
`success #12b76a` · `warning #f79009`(+fg `#93370d`) · `error #d92d20` · `info=link #1570ef`。浅底上文字用对应 `-fg`，对比 ≥ 4.5:1。

### 2.4 排版
- `--ph-font-sans`：系统优先（`-apple-system`/`Segoe UI`/`PingFang SC`/微软雅黑/思源黑回退，Inter 仅命中已装，不强制下载）。
- `--ph-font-mono`：`SF Mono`/`JetBrains Mono`/`Consolas`（件号 / SKU 码 / 供应商 code / 构成树）。
- 类型阶（13px 基准 · 比率 1.2 · 行高对齐 4px）：`xs 12/16` `sm 13/20`(正文基准) `base 14/20` `lg 16/24` `xl 20/28` `2xl 24/32`(KPI 数字) `3xl 30/36`。
- 字重 3 档：`400 / 500 / 600`（全站 700 一律降 600）。
- **`.ph-num { font-variant-numeric: tabular-nums; }`**：全局铺到所有数字 / 价格 / 交期 / 计数 / SKU 件号列（当前完全缺失，B2B 专业感最廉价提升），价格列额外右对齐 + success 色。

### 2.5 间距（4px 网格）· 圆角 · 阴影 · 动效
- 间距：`1=4` `2=8` `3=12` `4=16` `5=20` `6=24` `8=32`（杜绝 5/7/10/15/18）；`el-row gutter` 统一 12。
- 圆角：`xs 4` / `sm 6`(控件/按钮) / `md 8`(卡片/弹层) / `full`。`--el-border-radius-base→8`，`.el-button` 单独锁 6。
- 阴影 4 档（映射 M3 标高）：`sm`(卡片默认) / `md`(hover 抬升) / `lg`(下拉/popover) / `overlay`(对话框/抽屉)。层级靠**细边框 + 极轻阴影**而非重色块（Linear/M3 inset 风格）。
- 动效：`fast 150ms`(微交互) / `base 200ms`(层级进出) / `ease cubic-bezier(.2,0,0,1)`；`@media (prefers-reduced-motion) 归零`。

### 2.6 双角色密度（`html[data-density]`，默认随角色，localStorage 持久化）
- **comfortable**（业务员）：行高 ~48、卡片 pad 16、`--el-component-size 32`。
- **compact**（管理员）：行高 ~40-44、卡片 pad 12、`--el-component-size 28`/`-small 24`、表格 cell padding 收紧；重表页默认 `el-table size=small`。零页面 template 改动。

### 2.7 暗色（`html.dark` 覆盖同名 `--ph-gray-*`）
Carbon g90/g100（`gray-0 #1a1d23`/`50 #14161a`/`900 #f2f4f7`，"提对比而非加深阴影"）；品牌提亮一档（brand-500）；语义浅底转 `rgba(色,.16)` 叠色；`main.ts` 引 `element-plus/theme-chalk/dark/css-vars.css`。因 `--el-*` 已指向 `--ph-*`，全自动适配。

## 3. EP 变量重绑（运行时，零页面改动）
`--el-color-primary→brand-600`；`success/warning/danger→`语义色，`info→gray-600`；文本四级`→gray-900/700/600/500`；边框`→gray-300/200/200/100`、`-dark→gray-400`；填充`fill→gray-100`/`fill-light→gray-50`/`bg→gray-0`/`bg-page→gray-50`；圆角 base 8/small 6；阴影 4 档；`font-family→ph-font-sans`。

## 4. 组件库

| 组件 | 规格要点 |
|---|---|
| **StatCard.vue**（唯一最重要新增）| 统一全站 5 处异构指标卡。白底+1px gray-200+radius 8+pad 16+shadow-sm，左 3px tone 色条；label 12 gray-600 / value 24·600·`.ph-num`·gray-900。`tone: default/brand/success/warning/danger/info`；`clickable` hover→brand 边+shadow-md+`translateY(-1px)`+键盘可达；`active` brand 边+light-9 底。替换 SkuList stat-band/ov-band、Suppliers dash/sc-metrics、PartDetailDrawer pd-stat，删约 40 行 scoped CSS。 |
| **数据表格**（全局 `:deep`）| 表头 gray-50 底 + gray-600 13px medium；行 hover gray-50；数字列 `.ph-num` 等宽、价格右对齐 success；重表页 `size=small`。 |
| **按钮** | 圆角锁 6；primary 实心 brand / hover brand-500 / active brand-700；尺寸随密度。 |
| **标签徽章** | 成对语义色 + 共享 `constants/status.ts`（收编 PartsTable/PartDetailDrawer 重复 statusMap）。 |
| **PageHeader.vue / Toolbar.vue**（薄包装·渐进接入）| 吸纳各页散落 h2/h3/h4 标题与 6 处内联工具条。 |
| **对话框/抽屉/分段/空状态** | 自动吃 radius 8 + shadow-overlay；进出 base+standard 曲线轻位移淡入；空状态统一 image-size + gray-600 描述。 |
| **MainLayout 外壳** | 侧栏 logo 方块 + 菜单分组标题 + active 左 3px brand inset 条；topbar 56px + shadow-sm + 圆形 avatar + 角色 chip + 密度/暗色开关。逻辑/路由/搜索/购物车零改。 |

## 5. 实施路线（演进式 · 分期可回退）

| 阶段 | 范围 | 工作量 |
|---|---|---|
| **P0 地基**（阻塞后续）| 新建 styles/* + `main.ts` 换入口 + 加 sass；`npm run build` 验证梯度生成 | M |
| **P1 收编 hex + 全局换肤验收** | 6 行 hex → 令牌；逐页 GUI 对照零回归（解锁暗色）| S |
| **P2 StatCard + 等宽数字 + statusMap 消重** | 专业感核心红利，纯展示层 | M |
| **P3 外壳精修 + 密度开关** | logo/分组/active 条、topbar avatar、紧凑/宽松/暗色开关 | M |
| **P4 逐屏精修 + 薄包装渐进接入** | 配置看板工作台外壳、报价结算条、模板上传区等（分批·非阻断）| L |
| **P5 暗色上线**（演进项·可后置）| `html.dark` 覆盖灰阶 | M |

## 6. 关键风险（落地必盯）
1. **梯度脱节**（最高优先）：primary-light-3..9 必须 SCSS 编译期重算，否则 `.active` 浅底撞色。
2. **sass 缺失致 build 失败**：P0 先装并同步 lockfile / CI。
3. **第 7 处 hex**：`Suppliers.vue:281` 的 `color:#fff` 须与背景一起改（否则浅底白字看不见）。
4. **compact 可读性**：AdminTemplates（操作列最多 5 按钮）需专门手测点击命中率，必要时操作列保留宽松间距。
5. **首帧 FOUC**：density/dark 须在挂载前（index.html 内联或 main.ts 最早处）读 localStorage 打 class。
6. **零回归须验证非声称**：每阶段先科学自测（build + 逐页对照）→ 用户 GUI 手测验收；配置看板 350ms 防抖、PartPicker 400ms 查重、cart store 契约等命脉，换肤绝不可触碰。

---
*Sources: Element Plus theme-chalk SCSS、IBM Carbon、Vercel Geist、Linear、Shopify Polaris、Material 3、Ant Design Pro、shadcn/ui。*
