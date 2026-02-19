# PRD：Telegram 卡片 → Google Sheets 公共看板（卡片块 x,y 渲染 + 全字段无遗漏审计）

## 0) 一句话定义

把现有 Telegram（TG）前端“卡片消息”同步到一个 **Google Sheets（公开只读）** 工作簿中：
- **展示面（默认：覆盖写看板）**：在 `看板` 里把每张卡片画成一个二维块（x=列区间，y=行起点，height=卡片高度），**同类卡片每次同步覆盖替换旧块**，禁止“持续向下堆叠”。展示面支持两种口径：
  - `dashboard`（推荐默认）：每轮 **reset 看板并全量重绘**，按卡片实际高度紧凑排布，天然不会出现“卡片间空洞/错位”。
  - `replace slot`（可选）：按 `card_type` 固定槽位 y 覆盖写，适合需要“卡片位置长期稳定”的场景，但必须处理“高度变小导致空洞”的问题。
- **事实面**：以“索引 + EAV（键值）+ 外部 Blob 引用”的方式 **完整留存所有字段与原始内容（无遗漏）**，支持筛选统计、审计追溯、以及重放重建看板。

> 关键前提：公开可读 ≠ 匿名可写。任何自动写入必须通过有编辑权限的身份（Apps Script Webhook 或 Service Account）。

---

## 1) 背景与问题

### 1.1 现状
- TG 内持续产出多类卡片：排行榜/快照/信号/异常/运行状态等。
- 数据以消息流存在：不利于批量检索、跨币种对比、统计、复盘与审计。

### 1.2 你提出的“表格化”本质
你要的不是“把卡片解析成一行表”，而是同时满足两件事：
1) **像 TG 一样看**：卡片占据固定列段、卡片内结构清晰；看板上同类卡片固定在一个槽位里覆盖更新，不滚动堆叠。
2) **像数据库一样查**：任何字段都不丢（包括未知字段、未来新增字段、原始文本/JSON）。

---

## 2) 目标 / 非目标

### 2.1 目标（必须）
1) **全卡片覆盖**：TG 现有卡片类型都能写入（至少以 raw + EAV 的形式落盘）。
2) **全字段无遗漏**：字段集合不可预设，必须做到“来什么记什么”，且能回溯原始内容。
3) **幂等写入**：重复投递同一卡片不会产生重复事实记录；看板不出现重复块。
4) **旁路不阻塞**：写 Sheets 失败不影响 TG 主链路（outbox + 重试）。
5) **可重建**：看板属于派生展示面，可由事实表重放重建。

### 2.2 非目标（明确不做）
- 不把逐笔/订单簿等高频明细作为 Sheets 主仓。
- 不在 Sheets 内做强事务、强一致的数据库能力。

---

## 3) 关键约束（Google Sheets 硬限制）

### 3.1 写入身份
公开表格只能匿名只读；自动写入必须走：
- B) Service Account + Sheets API（默认：纯 CLI/无需网页部署）
- A) Apps Script Webhook（可选：用个人账号写入，适合 Drive blob/权限编排）

#### B 模式（Service Account）CLI 快速开始（无网页部署 Apps Script）

认证要点：
- 使用 **Service Account JSON key**（保存为本地文件），服务端通过 `GOOGLE_APPLICATION_CREDENTIALS` 指向该文件完成认证。
- 需要在 GCP 项目里启用 `Google Sheets API` 与（可选但建议）`Google Drive API`（用于 public/share 与 blob）。

TradeCat 侧（`sheets-service`）最小命令序列：

```bash
cd services/consumption/sheets-service
make install

export SHEETS_WRITE_MODE=sa
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa-key.json"

# 1) 创建/初始化工作簿（输出 spreadsheet_id 与 URL）
.venv/bin/python -m src --bootstrap --bootstrap-title "TradeCat TG Cards Dashboard"

# 2) 把输出的 spreadsheet_id 写入环境变量后开始同步
export SHEETS_SPREADSHEET_ID="..."
.venv/bin/python -m src --once --cards super_trend_ranking,macd_ranking,bb_ranking
```

注意：
- 若 Service Account 的 **Drive 存储配额为 0**，`--bootstrap` 无法创建新工作簿。解决方案：用个人账号先创建一个空 Google Sheet（网页端），把该工作簿分享给 SA 邮箱为编辑，然后直接设置 `SHEETS_SPREADSHEET_ID` 走写入即可。
- Sheets API 默认写入配额通常较低（常见 `WriteRequestsPerMinutePerUser=60`），建议设置 `SHEETS_SA_WRITE_RPM=50` 做客户端限流，避免稳定触发 429。
- 看板模式建议：`SHEETS_SYNC_MODE=dashboard`（SA 默认），每轮重绘看板，避免 slot 预留高度导致“间隙/错位”；版式更新后可用 `--force` 强制刷新。

### 3.2 容量与性能
Sheets 有单元格字符上限、工作簿 cell 总量上限（约 1000 万）、脚本执行时间与配额限制。

**因此结论：**
“无遗漏”不能靠把所有 raw 文本/JSON 都塞进单元格。必须支持：
- 表内存“索引/摘要/结构化字段”
- 超长内容落到外部 Blob（Google Drive 文件或对象存储），表内存引用与 hash 校验

> 现实补充：当工作簿触发 1000 万 cells 上限时，事实表的 append 会失败；此时必须将 `SHEETS_FACTS_MODE=none`，让系统退化为“仅展示面（看板）覆盖写”，避免服务整体卡死在 outbox。

---

## 4) 总体方案（标准分层：事实表 + 渲染表）

### 4.1 工作簿 Sheet 规划（标准）

```text
+------------------+--------------------------------------------------------+
| Sheet            | 职责                                                   |
+------------------+--------------------------------------------------------+
| 看板              | 展示面：卡片块 x,y 渲染（固定列宽、可变高度）           |
| 卡片索引          | 索引面：一卡一行（幂等键/时间/类型/TG 链接/渲染坐标）   |
| 卡片字段EAV       | 事实面：卡片级“所有字段”EAV（字段无限扩展，不遗漏）     |
| 卡片明细行        | 事实面：表格型卡片的“明细行骨架”（rank/symbol 等）      |
| 明细字段EAV       | 事实面：明细行的“所有字段”EAV（字段无限扩展，不遗漏）   |
| 大字段索引        | 外部大字段引用：raw_text/raw_json（URL + hash + size）  |
| 元数据            | 状态：dashboard_next_row、schema_version、统计等        |
+------------------+--------------------------------------------------------+
```

> 兼容：历史工作簿若使用英文 tab 名（`dashboard/cards_index/.../meta`），服务端会自动迁移为上述中文 tab 名（不丢 sheetId/历史数据）。

### 4.2 为什么要 EAV（键值表）
你要求“全部卡片全部字段无遗漏”，字段集合不可预先穷举；EAV 可以保证：
- 新字段出现无需改表结构
- 字段用 `field_path`（层级路径）表达，不丢语义
- 看板渲染失败也不影响事实落盘

---

## 5) 数据契约（Schema & 幂等）

### 5.1 幂等键（card_key）
必须稳定可复现，优先级推荐：
1) 卡片对应 TG 消息：`tg:{chat_id}:{message_id}`
2) 非 TG 消息但有 run：`run:{run_id}:{card_type}:{ts_epoch_ms}`
3) 否则：`hash:{sha256(canonical_json)}`

### 5.2 `cards_index`（一卡一行，主索引，append-only）

```text
card_key (PK)
ts_utc, ts_shanghai
source_service
card_type
title
dataset, period, sort_key, sort_order, limit
rows_count
dash_sheet, dash_col_l, dash_col_r, dash_row_y, dash_height
tg_chat_id, tg_message_id, tg_url
run_id
raw_text_blob_ref, payload_blob_ref
created_at_utc
```

### 5.3 `card_fields_eav`（卡片字段 EAV）

```text
eav_key (PK) = {card_key}:{seq}
card_key
scope          (card/header/params/hint/raw/...)
field_path     (例如 header.update_time / params.period / hint.text)
value_type     (text/number/bool/json/blob_ref)
value_text
value_number
value_json
blob_ref_id
```

### 5.4 `card_rows` + `row_fields_eav`（表格型卡片明细）
当卡片内部有“排行表/明细表”时，必须额外落明细层，保证可筛选/透视：

`card_rows`：
- `row_key (PK)`：`{card_key}:r:{rank}`（最稳）或 `{card_key}:r:{symbol}`
- `card_key, rank, symbol, symbol_full, row_ts_utc`

`row_fields_eav`：
- `eav_key (PK)`：`{row_key}:{field_path}` 或 `{row_key}:{seq}`
- `row_key, card_key, field_path, value_type, value_* , blob_ref_id`

### 5.5 `blobs_index`（外部大字段引用）
用于“无遗漏”的底座：

```text
blob_ref_id (PK) = blob:{sha256}
card_key (nullable)
row_key  (nullable)
kind     (tg_raw_text/payload_json/render_snapshot/...)
mime
storage_url
sha256
size_bytes
created_at_utc
```

---

## 6) 看板渲染标准（你要的 x,y + i）

### 6.1 固定列宽
`看板` 选定固定列区间 `[COL_L..COL_R]`，所有卡片都写在这一段列中。
- 默认：从第一列开始渲染；若开启 7 周期横向（`SHEETS_EXPORT_MULTI_PERIODS=1`），默认右边界放宽到 `BS`（71 列）以容纳多周期字段。
- 可配置：`SHEETS_DASHBOARD_COL_L` / `SHEETS_DASHBOARD_COL_R`
- 推荐：开启 `SHEETS_DASHBOARD_AUTO_WIDTH=1`（dashboard 模式默认），根据本轮最大列数自动扩宽右边界，避免“超宽表头被纵向分块”让人误以为列丢失。

### 6.2 看板模式（必须写死：避免“持续堆叠”）
展示面有两层开关：
- 同步口径（`SHEETS_SYNC_MODE`）：
  - `dashboard`：每轮 reset 看板并全量重绘（推荐默认，紧凑排布，无空洞/不堆叠）
  - `snapshot`：outbox + 幂等增量写（写新事件，适合事实表 append 的场景）
- 渲染口径（`SHEETS_DASHBOARD_MODE`，主要对 `snapshot` 有意义）：
- `replace`（默认）：**按 card_type 固定槽位覆盖写**。第一次出现某 card_type 时分配一个 y 起点并写入 `元数据.slot.<card_type>.y`；后续永远在该 y 覆盖渲染。
  - `SHEETS_DASHBOARD_SLOT_HEIGHT`：槽位“最小预留高度”（行数）。实际预留高度会取 `max(最小预留高度, 当前卡片渲染高度)` 并记录在 `元数据.slot.<card_type>.h`，用于后续精确清理与必要时扩容下移。
- `append`（可选）：按 `meta.dashboard_next_row` 持续追加（审计流水视角，可能造成看板无限增长）。

### 6.3 固定版式（强约束，脚本好写）
记明细行数为 `N`，看板列宽为 `W = COL_R - COL_L + 1`，明细列数为 `C=len(columns)`，则：
- `chunks = ceil(C / W)`（若超宽则纵向分块渲染，但 **不丢列**）
- 表头行数 `H`：
  - 若 `columns` 存在 `字段@周期`：`H=2`（字段组表头 + 周期表头）
  - 若 `columns` 不含 `@`：`H=1`（单行列名表头）
- 卡片高度：`i = 1 + chunks*(H + N) + 1`
- y+0：源信息（合并 COL_L..COL_R）：`📊标题 ⏰更新 📊排序 💡提示 ⏰最后更新`（固定顺序拼接在同一单元格）
- y+1：表头（真实列；超宽时每个 chunk 都会有一行）
  - 若 `H=2`：y+1=字段组表头，y+2=周期表头
  - 若 `H=1`：y+1=单行列名表头
- y+(1+H)..：明细行（真实列；超宽时每个 chunk 都会重复渲染 N 行）
- y 末尾：1 行空行分隔（预留但不写值）

下一张卡片起点：`y_next = y + i`

### 6.3 `meta.dashboard_next_row`（唯一写入指针）
`dashboard_next_row` 必须在 Webhook 侧用锁保护（并发写入会撞块）。

---

## 8) 多周期横向（7 周期）展示规则（新增：看板核心诉求）

当卡片属于“排行榜类”且存在 `<prefix>_period` 的周期状态键时，导出器默认生成“多周期横向表”：
- 字段口径：**保留单周期卡片的全部字段（表头不丢）**，并把“周期”展开为横向列。
  - 例：若单周期表头为 `排名/币种/趋势强度/持续根数/方向/量能偏向/成交额/...`
  - 则多周期列为：`币种` + `排名@1m..排名@1w` + `趋势强度@1m..趋势强度@1w` + `持续根数@...` + ...
- `sort_desc` 统一标记为：`多周期 <原字段>(🔽)`，避免误导为单一周期（例如只显示 15m）

### 8.1 多周期纵向（周期为行 / 字段为列）展示规则（新增：为冻结列与统一宽度服务）
当你希望 **宽度统一、可冻结列**（例如冻结 `币种` 与 `周期` 两列）时，建议将“多周期横向表”转为纵向表：
- 表头：`币种 | 周期 | <字段1> | <字段2> | ...`（每个字段只占 1 列）
- 行：每个币种拆成 7 行（`1m,5m,15m,1h,4h,1d,1w`），每行对应一个周期的字段值
- 配色：按“周期行”灰白交替，提升阅读与比对效率

> 关键约束：若 sheet 需要冻结列，则 **禁止** 对源信息行做“整行 mergeCells”（Sheets 禁止跨冻结列边界合并单元格）。

---

## 7) 接口设计（可选：Apps Script Webhook）

### 7.1 什么时候需要 Webhook
- 你要求“Google 在线表格作为函数”：Apps Script 的 `doPost()` 天然就是函数入口。
- 服务端只要 HTTP POST JSON，不需要在服务端维护 Google API 凭证复杂度。
 - 若需要 Drive blob 且不想受 SA Drive 配额限制：Webhook 走个人账号最稳。

### 7.2 Endpoint
- `POST https://script.google.com/.../exec`

### 7.3 鉴权（必须）
建议默认：HMAC + 时间窗 + nonce
- Header：
  - `X-TC-Timestamp`: Unix ms
  - `X-TC-Nonce`: UUID
  - `X-TC-Signature`: `hex(hmac_sha256(secret, timestamp + '.' + nonce + '.' + body))`
- 校验：
  - timestamp 在 ±5min 内
  - nonce 未使用过（简化版：存最近 N 个 nonce + 5min TTL）

> 兼容性注意：Apps Script 对自定义 Header 的读取不稳定，建议客户端同时把上述三项复制到 query 参数（双通道鉴权）。

### 7.4 请求体（CardEvent，schema_version=1）
```json
{
  "schema_version": 1,
  "card_key": "tg:123:456",
  "ts_utc": "2026-02-17T05:15:00Z",
  "source_service": "telegram-service",
  "card_type": "supertrend_rank",
  "header": {
    "title": "📈 超级趋势数据",
    "update_time": "2026-02-17 05:15:00",
    "sort_desc": "15m 趋势强度(🔽)"
  },
  "params": {
    "dataset": "trend",
    "period": "15m",
    "sort_key": "trend_strength",
    "sort_order": "desc",
    "limit": 10
  },
  "table": {
    "columns": ["rank", "symbol", "trend_strength", "price"],
    "rows": [
      {"rank": 1, "symbol": "BTCUSDT", "trend_strength": 3.14, "price": 623.02}
    ]
  },
  "hint": { "text": "..." },
  "tg": { "chat_id": 123, "message_id": 456, "url": "https://t.me/xxx/456" },
  "raw": {
    "telegram_text_full": "（可选，可能很长）",
    "payload_json_full": { "..." : "..." }
  }
}
```

### 7.5 响应体
```json
{
  "ok": true,
  "card_key": "tg:123:456",
  "idempotent": true,
  "dashboard": { "sheet": "看板", "col_l": "A", "col_r": "M", "row_y": 1201, "height": 17 }
}
```

### 7.6 幂等行为
- 若 `cards_index` 已存在该 `card_key`：
  - 返回 `idempotent=true`
  - 不重复写事实、不重复渲染
  - 运维重建：通过 CLI `--rebuild-dashboard` 从事实表重建看板（展示面可随时重建）

---

## 8) 处理流程（端到端）

### 8.1 服务端（默认：sheets-service）侧：旁路 outbox
MVP 默认不改 telegram-service：由 `sheets-service` 复用 cards 插件从本地 SQLite 生成 CardEvent，并旁路同步到 Sheets。
1) sheets-service 读取本地数据并导出 CardEvent（结构化 + raw + rows）
2) 写入 outbox（JSONL/SQLite 均可；默认 JSONL + checkpoint）
3) 后台 worker 批量 flush 到 Sheets（SA API 或 Webhook；失败指数退避重试）

> 增强（可选）：后续可在 telegram-service 的发送/编辑入口增加 hook，把真实 tg_url/chat_id/message_id 作为幂等键写入 outbox，实现“以 TG 消息为真相源”的同步。

### 8.2 Webhook（Apps Script）侧：先事实后渲染
顺序必须固定，才能保证“无遗漏 + 可重建”：
1) 鉴权（HMAC）
2) 幂等检查（cards_index 是否已有 card_key）
3) 落事实：`cards_index + card_fields_eav + (card_rows/row_fields_eav) + blobs_index`
4) 取锁 + 分配 y（meta.dashboard_next_row）
5) 渲染看板块（批量写 range + 合并单元格 + 样式）
6) 更新 meta.next_row
7) 返回 (y,height)

---

## 9) 失败降级与重试（必须）

### 9.1 不允许的失败模式
- 写表失败导致 TG 主链路失败（禁止）
- 看板渲染失败导致事实也丢（禁止）

### 9.2 允许的失败模式（可恢复）
- 看板渲染失败，但事实已落：后续可重建看板（从事实表重放恢复）
- raw 太大写不进单元格：落 blob，表内存引用

---

## 10) 可观测性（验收必需）

服务端：
- outbox backlog size、flush 成功率、p95 延迟、重试次数、最后错误

Webhook：
- QPS、成功率、锁等待时间、写入耗时、渲染耗时

---

## 11) 迭代计划（MVP → 完整）

### Phase 0（对齐契约）
- 固化 `card_type` 列表、schema_version、看板固定列区间与最大列策略

### Phase 1（MVP：先全量落事实）
- Webhook：写 `cards_index + card_fields_eav + blobs_index`
- 看板可先只写 title/update（验证链路）

### Phase 2（表格型卡片明细化）
- 补 `card_rows + row_fields_eav`
- 让 Sheets 透视表/筛选跑起来

### Phase 3（完整看板渲染）
- x,y 块渲染（表头 + 明细 + footer + 样式）
- 加入 `rebuild_dashboard(from_ts,to_ts)` 运维能力

---

## 12) 验收标准（Acceptance Criteria）
1) 任意卡片在 60 秒内可出现在 Sheets：至少 `cards_index` + `card_fields_eav` 落盘
2) 无遗漏可验证：raw_text / raw_json 可由 `blobs_index` 引用找回，hash 校验一致
3) 幂等可验证：同一卡片重复投递 10 次，事实表不重复，看板不重复
4) 失败不阻塞可验证：断网期间 TG 正常发消息；恢复后 outbox 自动补写
5) 看板可重建：清空看板后能从事实表重放恢复

---

## 13) 需要你拍板的 4 个决策（会影响实现细节）
1) `看板` 固定列区间：用哪段（默认 A..M）？
2) “超宽字段”策略：拆块（推荐）还是折行/截断？
3) Blob 存储：Drive 还是对象存储？（Drive 最快落地）
4) 是否需要“按 symbol 子表”（BTCUSDT）？（建议做派生视图，不强制每币建 sheet）
