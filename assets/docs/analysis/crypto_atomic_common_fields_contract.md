# Crypto 原子事实表“公共字段”契约（官方字段 + 公共字段）

> 目标：把所有 `crypto.raw_*` 原子事实表收敛成同一种可长期运行的形态：  
> **每一行 = 官方字段（Vision CSV） + 公共字段（固定宽度维度键）**。  
>
> 说明：这里的“公共字段”不是过程字段（不含 `file_id/ingested_at/time_ts`），而是**维度键**（固定宽度、可索引、可压缩、可长期演进）。

---

## 1) 公共字段是什么（定义）

公共字段（必须存在于所有“按 symbol 粒度”的原子事实表）：

- `venue_id BIGINT`：交易场所 ID  
  - 真相源：`core.venue(venue_id, venue_code, ...)`
- `instrument_id BIGINT`：交易工具 ID（统一金融工具）  
  - 真相源：`core.instrument(instrument_id, ...)` + `core.symbol_map(venue_id, symbol -> instrument_id, effective_*)`

这两个字段的价值（说人话）：

- **固定宽度**：替代 `TEXT(exchange/symbol)` 做主键/索引，避免索引膨胀与写入放大。
- **跨数据集统一**：trades / bookTicker / bookDepth / metrics 等都能用同一套维度键联结与对齐（as-of 在 view 解决，不污染事实表）。
- **演进友好**：symbol 改名、合约滚动、同名 symbol 跨产品（spot/um/cm/option）都靠 `core.*` 维表治理，不靠事实表改列/改主键。

> 参考：`docs/analysis/crypto_trades_fact_table_pro_design.md` 的维度键方案与写库契约。

---

## 2) 公共字段怎么构造（唯一正确路径）

### 2.1 输入（采集侧天然拿到的东西）

构造 `(venue_id, instrument_id)` 只需要 3 个输入：

- `exchange`：例如 `binance`
- `product`：例如 `futures_um` / `spot` / `futures_cm` / `option`
- `symbol`：例如 `BTCUSDT`

### 2.2 规则（把 product 写进键空间，避免 future 扩展时撞车）

`venue_code = f"{exchange}_{product}"`（例如 `binance_futures_um`）

原因：

- spot/um/cm/option 会共享同名 `BTCUSDT`，必须让它们落在不同 `venue_id` 空间。

### 2.3 具体构造流程（CoreRegistry）

公共字段必须通过 `CoreRegistry.resolve_venue_and_instrument_id()` 生成：

1) 计算 `qualified_venue_code`（把 product 纳入 venue_code 键空间）
2) `UPSERT core.venue(venue_code=qualified_venue_code)` → 得到 `venue_id`
3) 事务级互斥锁：`pg_advisory_xact_lock(hashtext(venue_code), hashtext(symbol))`  
   - 防止并发“实时 + 回填”首次启动时重复创建 instrument / 重复插入 symbol_map
4) 查 `core.symbol_map` 当前映射（`effective_to IS NULL`）：
   - 有则复用 `instrument_id`
   - 无则创建 `core.instrument` + 插入 `core.symbol_map`
5) 返回 `(venue_id, instrument_id)` 并写入本地缓存（避免每行查库）

实现位置：

- `services/ingestion/binance-vision-service/src/writers/core_registry.py`

> 重要约束：`core.symbol_map` 必须应用硬约束脚本 `assets/database/db/schema/013_core_symbol_map_hardening.sql`，保证 active 唯一与有效期窗口自洽/不重叠。

---

## 3) 三种写入类型如何使用同一套公共字段（执行口径）

### 类型 #1：历史回填（Vision ZIP → CSV → DB）

- `symbol`：来自任务参数或文件路径（例如 `BTCUSDT`）
- `exchange/product`：由 dataset 固定（例如 `binance + futures_um`）
- 构造 `(venue_id, instrument_id)`：**每个 symbol 每个 run 只做一次**（不要 per-row resolve）
- 落库：`INSERT INTO crypto.raw_* (venue_id,instrument_id,官方字段...) ...`

### 类型 #2：实时写入（WSS / REST）

- WSS（优先）：订阅时已知 `(exchange,product,symbol)`  
  - 构造 `(venue_id, instrument_id)`：**启动时 resolve 一次并缓存**  
  - 每条事件只做“字段映射 + 批量写库”
- REST（兜底/监控）：仅当该数据集 REST 能 100% 对齐官方字段时才允许写入 raw 表  
  - 否则只能写治理旁路（runs/meta），禁止污染事实表

### 类型 #3：实时巡检回补（异步纠偏）

它本质上是“用治理表驱动的小窗 backfill/repair”：

- 巡检：根据 `ingest_watermark / ingest_gaps` 发现缺口
- 回补：对缺口时间窗触发 backfill（仍然走同一套 `(venue_id,instrument_id)` 构造）

注意：

- 对于无法从 REST 回放的事件流（例如某些 L1/L2 WS-only 数据），回补只能靠官方 ZIP（如果官方提供）或承认缺口并记录。
