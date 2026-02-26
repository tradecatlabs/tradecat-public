# 综合市场数据库规划与选型（基于当前 CSV 样本）

> 本文以你当前已落盘并验证过的样本为“唯一事实源”：
> `assets/artifacts/analysis/binance_vision_compass/BTCUSDT_20260211_010327/data/`
>
> 目标：先把 **多市场的“根结构 + 追溯层（storage）+ 加密资产落库（crypto）”** 定住；其他市场（美股/A股/港股/外汇/大宗/利率/基金/指数）先只建 schema 骨架占位，后续逐个补全事实表。

---

## 0. 选型结论（先能跑起来的 MVP）

### 0.1 结论

- **主库：PostgreSQL + TimescaleDB**（TradeCat 现有链路已在用，最小改动即可落地）
- **冷存：文件（zip/csv → parquet 可选）+ 元数据追溯表（storage.files）**

### 0.2 为什么这样选（由 CSV 规模推导）

以样本中的 `BTCUSDT` 为例（单日、单标的）：

```
futures/um/bookTicker  ≈ 13,562,778 行/天（CSV ~1.2GB）
futures/um/trades      ≈  8,784,246 行/天（CSV ~447MB）
spot/trades            ≈  7,167,427 行/天（CSV ~520MB）
bookDepth              ≈     33,949 行/天（CSV ~1.9MB）
metrics                ≈        289 行/天（CSV ~36KB）
BVOLIndex              ≈     86,388 行/天
EOHSummary             ≈      5,499 行/天
```

推论：
- `trades`、`bookTicker` 属于**高频海量事件**，长期全量写入 PostgreSQL 的成本很高（写入、索引、备份、vacuum 都会变成瓶颈）。
- 但 `metrics / bookDepth / klines / BVOLIndex / EOHSummary` 这类中低频数据非常适合放在 Timescale hypertable 中，压缩+分区可控。
- 因此：推荐把 **“官方目录对齐的原始文件”作为冷存真相源**，再把“你需要常用查询的那一部分”落到 Timescale 热库（可设置保留期）。

> 未来如果你要对“多标的、多年、tick 级全量事件”做交互式分析：建议新增 ClickHouse 作为专用分析引擎（可选，不是 MVP 必需）。

---

## 1. 输入数据事实（CSV 具体约束）

### 1.1 时间戳与 header 的硬约束

- `spot/*`：**无 header**；时间戳为 **epoch(us)**（微秒）
  - 解析必须“按路径 → 固定列序”，禁止猜 header。
- `futures/um/*`：多数有 header；时间戳多为 **epoch(ms)** 或 **datetime 字符串**
  - `bookDepth.timestamp` / `metrics.create_time` 为 datetime 字符串（样本中按 UTC 解析）
- `option/*`：
  - `BVOLIndex.calc_time` 为 epoch(ms)
  - `EOHSummary` 为 `date + hour` 语义（小时结束汇总）

### 1.2 订单薄相关（避免误解）

- `bookTicker`：只包含**买一/卖一**（L1），不包含更深档位。
- `bookDepth`：不是逐价位 L2 订单簿；是“**百分比档位深度曲线点**”（样本中每个 timestamp 固定 12 个 percentage 档位）。

---

## 2. 数据库分层与根结构（按市场类型分根，必须有子分支）

### 2.1 根结构（schema）

```
core        # 跨市场共享维表（instrument / symbol_map / calendar 等）
storage     # 文件追溯与导入水位（对齐外部目录/文件）

crypto      # 加密资产（先落地 Binance Vision CSV）
equities    # 股票（占位）
fx          # 外汇（占位）
commodities # 大宗商品（占位）
rates       # 固收与利率（占位）
funds       # 基金（占位）
indices     # 指数（占位）
```

### 2.2 crypto 子分支（按官方目录结构对齐）

> 你提出的强约束：**派生数据必须作为原子数据的子支**，并且“物理层只收集基元数据”；因此这里明确拆成两层。

```
crypto
  atomic（物理层：只收集基元数据；表名前缀 `raw_`）
    spot
      trades                 -> raw_spot_trades
    futures
      um
        trades                -> raw_futures_um_trades
        bookTicker             -> raw_futures_um_book_ticker   # 买一卖一（L1）
        bookDepth              -> raw_futures_um_book_depth    # 百分比档位深度曲线（不是逐价位 L2）
        metrics                -> raw_futures_um_metrics       # 交易所发布的衍生指标（mark/index/funding/OI 等口径聚合）
      cm
        trades                -> raw_futures_cm_trades         # 占位（结构与 um 对称）
        bookTicker             -> raw_futures_cm_book_ticker
        bookDepth              -> raw_futures_cm_book_depth
        metrics                -> raw_futures_cm_metrics
    option
      BVOLIndex              -> raw_option_bvol_index
      EOHSummary             -> raw_option_eoh_summary         # 语义上是汇总，但你要求强制归类到物理层

  derived（派生层：可选落库/缓存；表名前缀 `agg_`）
    spot
      aggTrades              -> agg_spot_agg_trades
      klines/1m              -> agg_spot_klines_1m
    futures
      um
        aggTrades              -> agg_futures_um_agg_trades
        klines/1m              -> agg_futures_um_klines_1m
        markPriceKlines/1m     -> agg_futures_um_mark_price_klines_1m
        indexPriceKlines/1m    -> agg_futures_um_index_price_klines_1m
        premiumIndexKlines/1m  -> agg_futures_um_premium_index_klines_1m
      cm
        (同 um 结构，占位表；agg_futures_cm_*)
```

> 落库映射（对应 DDL 事实）：
> - 物理层（atomic）→ schema `crypto.*`
> - 派生层（derived）→ 仍在 schema `crypto.*`（按“表集合/执行脚本”区分，不另建 schema）

> 重要：
> - `daily/monthly` 不进表名；`frequency` 记录在 `storage.files.frequency`。
> - “逐行 file_id 回溯”不是强制要求：对高频事实表（例如 `raw_futures_um_trades/raw_futures_um_book_ticker/raw_futures_um_book_depth`）为控制索引与写入放大，
>   默认不在事实表存 `file_id/ingested_at/*_ts`，证据链在 `storage.*` 与 `crypto.ingest_runs` 完成。

---

## 3. 表设计原则（对齐 CSV + 可追溯 + 幂等）

### 3.1 一条铁律：可追溯

- 每张落库表都带 `file_id` → `storage.files(file_id)` 外键（或至少同名列），实现“任意一行可回到来源文件”。

### 3.2 幂等键（避免重复导入）

按样本字段设计的建议主键/唯一键：

- `trades`：`(symbol, time_ts, id)`
- `aggTrades`：`(symbol, transact_time_ts, agg_trade_id)`
- `bookTicker`：`(symbol, event_time_ts, update_id)`
- `bookDepth`：`(symbol, timestamp, percentage)`
- `metrics`：`(symbol, create_time)`
- `klines_1m`：`(symbol, open_time_ts)`
- `BVOLIndex`：`(symbol, calc_time_ts)`
- `EOHSummary`：`(symbol, hour_ts)`

### 3.3 时间字段：保留原字段 + 统一可查询字段

- epoch(ms/us) 原值保留为 BIGINT（对齐 CSV）
- 同时生成 `*_ts`（TIMESTAMPTZ）用于分区/索引/统一查询
  - 本次 DDL 把 `*_ts` 作为**普通列**（非 generated），并要求**导入时计算**
    - 原因：Timescale hypertable 的 time dimension 不能使用 generated column（会导致 `create_hypertable` 失败）
    - 示例：`to_timestamp(time / 1000.0)` 或 `to_timestamp(time / 1000000.0)`

---

## 4. 落地文件（DDL）

已新增可执行 DDL（按顺序执行）：

- `libs/database/db/schema/008_multi_market_core_and_storage.sql`
  - 创建：`core.*` 与 `storage.*`
- `libs/database/db/schema/009_crypto_binance_vision_landing.sql`
  - 创建：`crypto.*`（对齐 Binance Vision CSV，含 Timescale hypertable + 压缩策略）
- `libs/database/db/schema/010_multi_market_roots_placeholders.sql`
  - 创建：`equities/fx/commodities/rates/funds/indices` schema 占位
- `libs/database/db/schema/011_crypto_binance_vision_derived.sql`
  - 创建：`crypto.*` 中的派生/汇总数据集（aggTrades/klines/*Klines；可选执行）

> 执行示例（按你实际 DB 名/连接串调整）：
>
> `psql "$DATABASE_URL" -f libs/database/db/schema/008_multi_market_core_and_storage.sql`
> `psql "$DATABASE_URL" -f libs/database/db/schema/009_crypto_binance_vision_landing.sql`
> `psql "$DATABASE_URL" -f libs/database/db/schema/010_multi_market_roots_placeholders.sql`
> `psql "$DATABASE_URL" -f libs/database/db/schema/011_crypto_binance_vision_derived.sql`  # 可选

---

## 5. 下一步（建议）

1) 先把 `storage.files` 接到现有 “binance_vision_compass” 导入流程里：做到“导入前先登记 file_id，导入后写 row_count/min/max”。
2) 明确热库留存策略：
   - `bookTicker/trades` 建议默认只保留近 N 天（否则数据量指数级爆炸）
   - 旧数据走 parquet 冷存（仍可通过 DuckDB/Spark/ClickHouse 查询）
3) 其他市场逐个补表时，优先复用同一套“根结构 + storage 追溯 + core.instrument 映射”。
