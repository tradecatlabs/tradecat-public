# Binance Vision 数据库物理设计（严格对齐目录结构）

> 目标：把 `data.binance.vision` 的**目录层级 + 文件命名 + CSV 字段**固化为一套可落地的数据库物理模型，做到：
> 1) 任何一行数据都能精确回溯到来源文件（可复现/可审计/可对账）；  
> 2) 导入具备幂等语义（重复写入无害，可重跑）；  
> 3) 在不破坏“目录结构对齐”的前提下，保留未来做统一查询/衍生层的演进空间。

本设计面向你当前的样本目录：`artifacts/analysis/binance_vision_compass/**/data/`，并以其中已验证的 CSV 事实为准（含：spot 无 header、spot 时间戳 us、futures 多为 ms、EOHSummary 的 date+hour 语义等）。

---

## 1. 这套“物理对齐目录结构”的设计合适吗？

结论：**适合作为“Binance Vision Landing Zone（落地区/落库区）”的物理设计**；不适合作为“全量高频事件的长期分析仓”。

### 1.1 适合的原因（为什么“对齐目录结构”有价值）

- **审计与可复现是第一优先级**：官方提供 `zip + checksum`，且历史文件可能更新/替换。把目录与文件名拆解成结构化字段（`market/product/frequency/dataset/symbol/interval/date`）并落到 `storage.files`，可以做到：
  - 对账：同一路径 `rel_path` 的 `sha256` 是否发生变化（回补/修复）
  - 增量：只导入“新增/变更”的文件
  - 追溯：任何一行都能回到 `rel_path`（满足“严格对齐”）

- **导入规则不靠猜**：目录层级本身就是 schema 的一部分（例如 `futures/um/daily/klines/.../1m/`），导入器按路径选择解析器，比“只看文件名”更稳健。

### 1.2 不适合的原因（需要明确边界）

- **高频 raw 表（trades/bookTicker）长期全量存 PG 成本极高**：写入量、索引空间、压缩、VACUUM、备份都会成为瓶颈。
- **目录结构是发布/归档模型，不是最佳查询模型**：若未来要跨 market/product 统一分析，仍需要“统一视图/衍生层”。

因此，本设计建议：把这些表定位为 **Landing Zone + 可控留存**，长期分析依赖衍生表（1s/1m 聚合）或外部列式存储（可选）。

---

## 2. 数据库与命名约定

### 2.1 数据库

- 方案 A（隔离优先）：建议新库 `binance_vision`（与现有 `market_data` 解耦，避免破坏历史服务与 schema）。
- 方案 B（单库多市场根）：如果你已经决定做“综合市场单库、多 schema”的统一设计，则建议复用同一个 PostgreSQL 数据库，并新增：
  - `storage.*`（文件追溯/导入水位）
  - `crypto.*`（Binance Vision 原子/物理层表：只收集基元数据）
  - `crypto.*`（Binance Vision 派生/汇总层表：仍在 crypto 根内，用“脚本/表清单”区分）
  - 其余市场根 schema 先占位（`equities/fx/...`）
  
  详见：`docs/analysis/multi_market_db_design.md` 与 `assets/database/db/schema/008_*.sql ~ 011_*.sql`。

### 2.2 目录结构到 schema/table 的映射规则（硬规则）

1) 顶层目录 → 市场根（schema）+ 表前缀：
- `data/futures/um/...` → `crypto.raw_futures_um_*`（物理层）与 `crypto.agg_futures_um_*`（派生层）
- `data/futures/cm/...` → `crypto.raw_futures_cm_*`（物理层）与 `crypto.agg_futures_cm_*`（派生层，占位）
- `data/spot/...`       → `crypto.raw_spot_*`（物理层）与 `crypto.agg_spot_*`（派生层）
- `data/option/...`     → `crypto.raw_option_*`（物理层；你要求 `EOHSummary` 强制物理）

2) dataset → table 名（必要时带 interval）：
- `klines/{symbol}/1m/` → `klines_1m`
- `metrics/{symbol}/` → `metrics`
- `bookTicker/{symbol}/` → `bookTicker`
- `aggTrades/{symbol}/` → `aggTrades`
- `trades/{symbol}/` → `trades`
- option：`BVOLIndex`、`EOHSummary` 直接对应同名表（大小写在 SQL 中统一小写或用引号固定）。

3) `daily/monthly` **不进表名**：
- `daily/monthly` 属于“来源文件属性”，严格记录在 `storage.files.frequency`，并由 `file_id` 外键实现逐行追溯。

> 这保证了：你仍能“按官方目录层级”查询，但避免 daily/monthly 双份事实表导致重复存储。

---

## 3. 总体结构示意图（你要求的“严格对齐”版本）

```text
------------------------------+
 DB: market_data (建议)        |
------------------------------+
 core/
   core.*                      # 跨市场维表（占位/锚点）

 storage/
   storage.files               # 对齐目录结构与文件命名的“真相源”
   storage.file_revisions
   storage.import_batches
   storage.import_errors

 crypto/                       # 原子/物理层：只收集基元数据
   crypto.raw_spot_trades
   crypto.raw_futures_um_trades
   crypto.raw_futures_um_book_ticker
   crypto.raw_futures_um_book_depth
   crypto.raw_futures_um_metrics
   crypto.raw_futures_cm_trades    (占位)
   crypto.raw_futures_cm_book_ticker
   crypto.raw_futures_cm_book_depth
   crypto.raw_futures_cm_metrics
   crypto.raw_option_bvol_index
   crypto.raw_option_eoh_summary   # 你要求强制物理

 crypto/                       # 派生/汇总层：仍在 crypto 根内（表集合区分）
   crypto.agg_spot_agg_trades
   crypto.agg_spot_klines_1m
   crypto.agg_futures_um_agg_trades
   crypto.agg_futures_um_klines_1m
   crypto.agg_futures_um_mark_price_klines_1m
   crypto.agg_futures_um_index_price_klines_1m
   crypto.agg_futures_um_premium_index_klines_1m
   crypto.agg_futures_cm_* (同 um 结构，占位)

 equities/ fx/ commodities/ rates/ funds/ indices/   # 其他市场根（先占位）
```

---

## 4. 核心表设计（字段对齐 CSV + 逐行回溯 file_id）

### 4.1 `storage.files`（严格对齐目录与文件名的“真相源”）

**职责**：1 行 = 1 个来源文件（zip 或 csv），并且把路径层级拆成结构化列。

建议字段（最小集合）：
- `file_id`（PK）
- `rel_path`（唯一，例：`data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-02-09.zip`）
- `market`：`futures|spot|option`
- `product`：`um|cm`（spot/option 为空）
- `frequency`：`daily|monthly`
- `dataset`：`klines|trades|aggTrades|bookTicker|bookDepth|metrics|BVOLIndex|EOHSummary`
- `symbol`：如 `BTCUSDT`；option 的 `EOHSummary` 还需 `underlying`（可放到 `storage.files.underlying`）
- `interval`：如 `1m`（无 interval 的 dataset 为 NULL）
- `file_date` / `file_month`：从文件名解析（按实际命名）
- `sha256`：来自 `.CHECKSUM`
- `size_bytes`
- `downloaded_at` / `extracted_at`
- `parser_version`：解析器版本（避免未来字段变化无法追溯）
- `row_count`、`min_event_ts`、`max_event_ts`（用于快速质量统计/范围裁剪）

### 4.2 `storage.file_revisions`（同一路径被替换的历史）

**职责**：当 `rel_path` 相同但 `sha256` 变化时记录版本链，解决“官方回补/修复”导致的对账问题。

建议字段：
- `rel_path`
- `old_sha256` / `new_sha256`
- `detected_at`
- `reason`（可选：例如 checksum 不一致）

### 4.3 时间字段的统一策略（ms vs us vs datetime）

为了“字段名对齐 CSV”，同时又能用 Timescale/索引高效查询：

- 对 epoch 列：保留原字段（BIGINT），再增加一个归一化列（TIMESTAMPTZ）：
  - futures ms：`*_ts = to_timestamp(epoch_ms / 1000.0)`
  - spot us：`*_ts = to_timestamp(epoch_us / 1000000.0)`
- 对 datetime 字符串列：直接落 `TIMESTAMPTZ`（按 UTC 解析）
- `EOHSummary`：`hour_ts = (date::date + hour hours)` 作为事实时间

> 这样保证：表结构与 CSV 对齐（原字段不丢），同时查询统一用 `*_ts`。

---

## 5. 每张事实表：字段/幂等键（对齐你当前样本）

统一约定：每张表都包含 `file_id` 外键以实现“严格对齐目录与文件名”。

### 5.1 Futures UM：`crypto.agg_futures_um_klines_1m`（派生层）

来源路径：
- `data/futures/um/{daily|monthly}/klines/{SYMBOL}/1m/*.csv`

CSV 字段（样本有 header）：
- `open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore`

建议列：
- `file_id`
- `symbol`
- `open_time` BIGINT（ms）
- `open_time_ts` TIMESTAMPTZ（归一化）
- 其余数值列对齐（NUMERIC 或 DOUBLE PRECISION，按你精度要求）

幂等键（唯一）：
- 建议与 DDL 一致：`PRIMARY KEY(symbol, open_time_ts)`

### 5.2 Spot：`crypto.agg_spot_klines_1m`（派生层）

来源路径：
- `data/spot/{daily|monthly}/klines/{SYMBOL}/1m/*.csv`

CSV 特性（样本无 header）：
- 列序与 futures 结构一致，但时间戳为 **us**。

建议列：
- `file_id`
- `symbol`
- `open_time` BIGINT（us）
- `open_time_ts` TIMESTAMPTZ
- 其余同列序映射（保持字段名与 futures 一致）

幂等键：
- 建议与 DDL 一致：`PRIMARY KEY(symbol, open_time_ts)`（open_time_us 只作为原字段保留）

> 注意：spot CSV 无 header，解析器必须以“路径→固定列序”为准，禁止猜测。

### 5.3 Futures UM：`crypto.raw_futures_um_metrics`（物理层）

来源路径：
- `data/futures/um/{daily|monthly}/metrics/{SYMBOL}/*.csv`

CSV 字段（样本有 header）：
- `create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio`

建议列：
- `file_id`
- `symbol`
- `create_time` TIMESTAMPTZ（或 TIMESTAMP + 约定 UTC）
- 其余数值列

幂等键：
- `UNIQUE(symbol, create_time)`

边界事实（来自样本）：
- 单日文件可能包含次日 `00:00:00`，不能用“文件名日期”硬切数据。

### 5.4 Trades / AggTrades（futures_um / spot 对称）

`crypto.raw_futures_um_trades`（物理层，header）：
- 维度键：`venue_id,instrument_id`（由 `core.venue/core.symbol_map` 把 `exchange/symbol` 字典化）
- 官方字段：`id,price,qty,quote_qty,time,is_buyer_maker`
- 幂等键：`PRIMARY KEY(venue_id, instrument_id, time, id)`
- `time`：BIGINT（ms）；**不存 `time_ts`**，展示时用 view/查询 `to_timestamp(time/1000.0)`
- 可读性：提供只读 view 映射回 `exchange/symbol`（避免用 TEXT 做主键导致索引膨胀）

`crypto.raw_spot_trades`（物理层，无 header）：
- 列序按官方定义与样本一致；`time` 为 BIGINT（us）+ `time_ts`
- 唯一：`UNIQUE(symbol, id)`

`crypto.*_agg_trades`（派生层，官方提供或可由 trades 聚合重建）：
- futures：`agg_trade_id,...,transact_time(ms),is_buyer_maker`
- spot：列序类似，但 transact_time 为 us
- 唯一：`UNIQUE(symbol, agg_trade_id)`

### 5.5 `crypto.raw_futures_um_book_ticker`（物理层）

来源路径：
- `data/futures/um/{daily|monthly}/bookTicker/{SYMBOL}/*.csv`

CSV 字段（header）：
- `update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time`

物理表列（落地版本，已收敛到 ids 事实表契约）：
- 公共字段（维度键）：`venue_id,instrument_id`
- 官方字段：`update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time`

幂等键（与 DDL 一致）：
- `PRIMARY KEY(venue_id, instrument_id, event_time, update_id)`

时间语义：
- `event_time`：BIGINT（epoch ms），Timescale integer hypertable 时间轴
- 不存 `event_time_ts`；展示时查询 `to_timestamp(event_time/1000.0)` 或使用只读 view

风险控制：
- 导入链路要做“乱序检测”（最少统计 `event_time` 是否单调、是否存在倒序段），必要时落盘前按 `(event_time, update_id)` 排序或记录质量告警。

### 5.6 `crypto.raw_futures_um_book_depth`（物理层，深度曲线）

来源路径：
- `data/futures/um/{daily|monthly}/bookDepth/{SYMBOL}/*.csv`

CSV 字段（header）：
- `timestamp,percentage,depth,notional`

物理表列（落地版本，已收敛到 ids 事实表契约）：
- 公共字段（维度键）：`venue_id,instrument_id`
- 官方字段：`timestamp,percentage,depth,notional`

时间语义：
- 官方 CSV 的 `timestamp` 是 UTC datetime；入库时统一转换为 `timestamp` BIGINT（epoch ms）
- Timescale integer hypertable 时间轴：`timestamp`

幂等键（与 DDL 一致）：
- `PRIMARY KEY(venue_id, instrument_id, timestamp, percentage)`

### 5.7 Option：`crypto.raw_option_bvol_index` / `crypto.raw_option_eoh_summary`（物理层）

`crypto.raw_option_bvol_index`（header）：
- `calc_time,symbol,base_asset,quote_asset,index_value`
- 唯一：`UNIQUE(symbol, calc_time)`
- `calc_time` BIGINT（ms）+ `calc_time_ts`

`crypto.raw_option_eoh_summary`（header，语义为 date+hour 的小时结束汇总；你要求强制物理）：
- `date,hour,symbol,underlying,type,strike,...,openinterest_*`
- 建议时间列：`hour_ts = date + hour`
- 幂等键建议：`PRIMARY KEY(symbol, hour_ts)`（与 DDL 一致；也可额外建 `UNIQUE(underlying, hour_ts, symbol)` 方便按标的裁剪）

---

## 6. 索引、分区（hypertable）、压缩与留存（建议）

> 这里是成熟实践中最容易踩坑的部分：你要同时考虑写入吞吐、查询裁剪、索引体积、压缩比、以及“重复导入”的 upsert 行为。

### 6.1 hypertable 选择

建议 hypertable：
- `crypto.*_klines_1m`（派生层，按 `open_time_ts`）
- `crypto.*_trades`、`crypto.*_agg_trades`、`crypto.*_book_ticker`（按 `time/event_time`）
- `crypto.*_metrics`（按 `create_time`）
- `crypto.*_book_depth`（按 `timestamp`，epoch ms）
- option 表按体量可选

### 6.2 chunk 粒度

经验建议（按数据量动态调）：
- `bookTicker/trades/aggTrades`：`1 day` chunk
- `klines_1m`：`7 days` chunk（也可 1 day）
- `metrics/bookDepth/option`：`7~30 days` chunk

### 6.3 压缩策略（Timescale）

典型建议：
- `segmentby = 'symbol'`
- `orderby = '<time_col> DESC'` 或 ASC（按查询模式）
- 压缩延迟：高频表 1~3 天后压缩；低频表 7 天后压缩

### 6.4 留存策略（强建议）

如果你坚持“全量落 PG”，至少要：
- 对 `bookTicker/trades/aggTrades` 设置较短留存（例如 7~30 天）
- 长期分析走“衍生表/外部列式存储”（可选扩展）

---

## 7. 演进空间：在不破坏“严格对齐”的前提下做统一查询

当你开始做跨 market/product 统一分析时，建议新增：

1) 统一视图层（不会破坏你要求的物理层级）
- `v.trades` = `UNION ALL crypto.raw_futures_um_trades + crypto.raw_futures_cm_trades + crypto.raw_spot_trades`（列对齐）
- `v.klines_1m` = `UNION ALL crypto.agg_futures_*_klines_1m + crypto.agg_spot_klines_1m`

2) 统一 instrument 映射（可选）
- `ref.instruments`：把 `BTCUSDT` 与期权合约符号统一建模，便于 join 与衍生计算。

> 重要：这些是“上层视图/维表”，不改变你当前“表结构对齐目录层级”的硬约束。

---

## 8. 最小落地清单（建议执行顺序）

1) 先建 `storage.*`（否则无法做到严格对齐与审计）
2) 建 `crypto.*`（物理层：基元数据 + option 强制物理）
3) 按需要再执行派生层脚本（仍创建在 `crypto.*`）：aggTrades/klines/*Klines（可选）
4) 再按节奏补 `equities/fx/...` 的事实表（综合市场扩展）

---

## 9. 结语（设计哲学）

目录结构对齐解决的是“可复现与审计”；事实表建模解决的是“可查询与计算”。  
把它们混成一件事（例如按 symbol/day 分表）会让系统在规模上崩溃；把它们分层（`storage.files` + 按 dataset 的事实表）才是长期可维护的做法。
