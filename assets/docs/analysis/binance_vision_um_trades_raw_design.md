# Binance Vision UM Trades Raw 表设计综述（含背景上下文）

> ⚠️ **Deprecated / 已废弃**  
> 本文记录的是“旧版 v1 事实表形态”（`exchange/symbol TEXT + NUMERIC`）。  
> 你已明确要升级到业内成熟方案：`venue_id/instrument_id BIGINT + DOUBLE`（短主键、固定宽度、成本可控），并用 view 恢复可读性。  
>
> 最新真相源请以以下文档/DDL 为准：  
> - `assets/docs/analysis/crypto_trades_fact_table_pro_design.md`（全局专业版设计）  
> - `assets/docs/analysis/binance_vision_um_trades_mature_playbook.md`（UM trades 落地手册）  
> - `libs/database/db/schema/009_crypto_binance_vision_landing.sql`（DDL 真相源）  

## 1. 背景上下文

你当前的数据工程目标是：

- 采集链路严格对齐 Binance Vision 官方数据产品语义；
- 先落地 **Raw/基元层**，后续再从 Raw 派生 agg/klines；
- 以模型训练、回测重放、派生计算为核心用途；
- 采集实现约束为 `ccxt/ccxtpro`（实时优先 WS）。

在这个背景下，`futures/um/trades` 被作为第一优先级数据集，因为它是最核心的逐笔原子成交流，可作为多个上层数据的共同源头。

---

## 1.1 全局决策（已确认）

- **落库位置**：继续使用 `market_data` 库下的 `crypto` schema（不新建独立 `binance_vision` 库）。
- **TimescaleDB**：允许并建议对该表启用 hypertable + compression；压缩策略先按 **30 天后压缩**。
- **时间列**：不新增 `time_ts`；事实表只保留 `time (BIGINT, epoch ms)`，展示时用视图/查询做 `to_timestamp(time/1000.0)`。
- **回填范围**：`monthly + daily` 都会导入；建议从 **2019**（UM 最早可用期）到现在。
- **回填/实时交接**：允许安全窗口（默认先用 **5 分钟**；可再调小/调大）。
- **同键不一致**：以回填（官方文件）为准，允许受控 UPDATE 修正差异列。
- **首批覆盖**：先只跑 `BTCUSDT`（后续再扩到更多 UM 永续）。
- **symbol 规范**：统一使用 Binance 原生 `info.s`（如 `BTCUSDT`；交割保留其官方后缀）。
- **实时接口**：`ccxtpro.watchTrades`；当前网络到 `fapi.binance.com` reset 时，实时会依赖“巡检 + REST 补齐/或等待官方文件回填兜底”。

---

## 2. 本次字段策略（你已确认）

你已明确确认以下策略：

- 保留官方字段完整性（官方 6 字段必须全量入库）；
- 只保留最小扩展字段：`exchange`、`symbol`；
- 不增加 `file_id`；
- 不增加 `ingested_at`；
- 不增加 `time_ts`（查询时由 PostgreSQL 动态转换显示）。

因此，该表总字段数为 **8**（官方 6 + 扩展 2）。

---

## 3. 字段定义（UM Trades）

### 3.1 官方字段（6）

1. `id`（BIGINT）  
   成交 ID（trade id）。

2. `price`（NUMERIC(38,12)）  
   成交价格。

3. `qty`（NUMERIC(38,12)）  
   成交数量（base）。

4. `quote_qty`（NUMERIC(38,12)）  
   成交额（quote）。

5. `time`（BIGINT）  
   成交时间戳（毫秒，epoch ms）。

6. `is_buyer_maker`（BOOLEAN）  
   买方是否是 maker。

### 3.2 扩展字段（2）

1. `exchange`（TEXT）  
   交易所代码（当前建议固定值 `binance`，为后续多交易所并表做准备）。

2. `symbol`（TEXT）  
   交易对（如 `BTCUSDT`）。

---

## 4. 表结构建议（DDL 参考）

```sql
CREATE TABLE IF NOT EXISTS crypto.raw_futures_um_trades (
    exchange        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    id              BIGINT NOT NULL,
    price           NUMERIC(38, 12) NOT NULL,
    qty             NUMERIC(38, 12) NOT NULL,
    quote_qty       NUMERIC(38, 12) NOT NULL,
    time            BIGINT NOT NULL,           -- epoch(ms)
    is_buyer_maker  BOOLEAN NOT NULL,
    -- 注意：若启用 Timescale hypertable，唯一键通常需要包含分片时间列；
    -- 因此建议把 time 一并纳入主键/唯一键。
    PRIMARY KEY (exchange, symbol, time, id)
);

-- 关键点：禁用 TimescaleDB 默认时间索引（*_time_idx）
-- 该表主键已覆盖核心查询路径；额外的 `time DESC` 索引会显著放大写入与存储成本。
SELECT create_hypertable(
  'crypto.raw_futures_um_trades',
  'time',
  chunk_time_interval => 86400000,        -- 1 day（单位=ms）
  create_default_indexes => FALSE,
  if_not_exists => TRUE
);
DROP INDEX IF EXISTS crypto.raw_futures_um_trades_time_idx;
```

索引策略（默认只保留 1 个主键索引）：

- `PRIMARY KEY (exchange, symbol, time, id)`：满足“按交易所+交易对按时间回放/抽样”的主路径；
- 不额外创建 `time DESC` 索引：避免冗余索引导致的写入放大与索引体积膨胀；
- 若未来有“跨全市场不带 symbol 的按时间取最新”需求，再按需加：`BRIN(time)` 或专用 `btree(time DESC)`（不要默认就建）。

---

## 5. 使用场景与目的

### 5.1 模型训练

- 提供 tick 级原子成交流；
- 可提取微观结构特征（成交方向、成交密度、短时冲击等）。

### 5.2 回测与重放

- 可做逐笔事件回放；
- 适用于成交驱动策略、滑点模型、执行质量评估。

### 5.3 派生计算

- 作为 `aggTrades`、`klines` 等派生层的唯一事实来源之一；
- 保证“先有原子，后有聚合”的可解释链路。

### 5.4 多交易所统一

- `exchange + symbol` 让未来接入 OKX/Bybit 等时无需改核心查询模式。

---

## 6. 查询时做时间转换（不落 time_ts）

```sql
SELECT
  exchange,
  symbol,
  id,
  to_timestamp(time / 1000.0) AS trade_ts_utc,
  price,
  qty,
  quote_qty,
  is_buyer_maker
FROM crypto.raw_futures_um_trades
WHERE exchange = 'binance'
  AND symbol = 'BTCUSDT'
ORDER BY time DESC
LIMIT 100;
```

---

## 7. 当前设计的取舍说明

### 优点

- 字段最小化，结构清晰；
- 与官方字段高度一致；
- 多交易所扩展路径明确（`exchange` 已预留）。

### 成本

- 没有 `file_id`：弱化文件级追溯/审计能力；
- 没有 `ingested_at`：弱化入库时效与重跑审计；
- 没有 `time_ts`：查询时需运行时转换，重时间查询场景会有额外计算成本。

---

## 8. 结论

在你当前“先快稳落地 Raw 原子层”的目标下，这个 8 字段设计是可执行且简洁的。  
如果后续进入生产审计与质量治理阶段，再按需补 `file_id` / `ingested_at` 即可。

---

## 8.1 回填粒度选择（daily vs monthly，避免重复）

你观察到的事实是正确的：**daily 与 monthly 本质是同一份事实数据的不同打包方式**。

因此回填应该遵循“智能选择”，避免两份都导入造成无意义重复：

- **整月覆盖（且不是当前月）**：优先导入 `monthly`（一个月 1 个 ZIP）
- **边界月/当前月**：按日导入 `daily`（月度 ZIP 可能未生成/不完整）
- **月度 ZIP 404**：自动降级到 daily

这样可以做到：

- 不重复写同一份数据；
- 下载次数最小；
- 对“从 2019 到现在”的全量回填最友好。

---

## 9. 表定位与边界（重要）

这张表被定义为 **“UM 合约逐笔成交（trade）事实表”**，其设计重点是：

- **事实优先**：字段对齐官方语义，尽量不引入“采集过程字段”污染事实表。
- **可派生**：允许从它派生 `aggTrades`、`klines`、微观结构特征等上层数据。
- **幂等写入**：允许“至少一次”写入语义（WS 重连/补拉/重放）而不产生重复行。

边界也需要明确：

- 这张表**不负责**文件级审计与回溯（你明确不加 `file_id`）；这意味着“Binance Vision 历史文件导入链路”与“ccxtpro WS 实时链路”在审计维度上会有所不同。
- 如果未来你确实要把 Vision 的 daily/monthly 文件导入到同一事实表中，建议在工程侧建立一套 **sidecar 元数据（run/batch/watermark）**，否则对账与缺口定位会很痛。

---

## 10. 幂等键、写入语义与异常策略

### 10.1 逻辑幂等键 vs 物理主键（Timescale 约束）

- **逻辑幂等键（你脑子里想要的）**：`(exchange, symbol, id)`  
  含义：同一个交易对里，trade id 应该唯一，所以重复写入应该被去重。
- **物理主键（你实际上落到库里的）**：`(exchange, symbol, time, id)`  
  原因：你启用 Timescale hypertable 且 `time` 是分片列时，**唯一键/主键通常需要包含分片时间列**，否则会被 Timescale 直接拒绝。

这带来的关键差异是：

- 正常情况下（同一笔 trade 重复到达时 `time` 不变），`ON CONFLICT (exchange, symbol, time, id)` 仍然能做到“重复不插入”。
- 但如果上游/解析 bug 导致 **同一个 `id` 被写入了不同的 `time`**，数据库不会自动挡掉（因为主键不同），你需要用审计 SQL 把它抓出来。

### 10.2 推荐写入模式（MVP）

```sql
INSERT INTO crypto.raw_futures_um_trades (
  exchange, symbol, id, price, qty, quote_qty, time, is_buyer_maker
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8
)
ON CONFLICT (exchange, symbol, time, id) DO NOTHING;
```

### 10.3 冲突行的“数据不一致”如何处理？

事实表的理想世界是：同一个幂等键永远对应同一行事实。

但工程世界里仍可能出现：

- 解析/精度差异导致写入值不同（例如 `float` → `NUMERIC` 的舍入误差）；
- 上游源在极端情况下出现回补/修正（很少见，但不是不可能）。

建议策略（不改表结构的前提下）：

- **实时链路（ccxtpro/WS）**：始终 `DO NOTHING`，保证吞吐与幂等。
- **回填链路（Binance Vision 官方文件）**：允许受控 `DO UPDATE`，只修正差异列（`price/qty/quote_qty/is_buyer_maker`），以官方文件为准。
- **审计**：定期跑“同 `id` 多行”检查；一旦出现，优先按“采集/解析 bug”处理，而不是业务正常现象。

---

## 11. 字段语义细节（避免训练/回测误用）

### 11.1 `is_buyer_maker` 的方向语义

`is_buyer_maker = true` 表示“买方为 maker”，也等价于：

- **taker 侧为卖方**（sell taker）
- 这笔成交更可能由“卖方主动吃单”触发

因此，如果你要构造常用的 `taker_side`，可以用：

- `taker_side = 'sell'` 当 `is_buyer_maker = true`
- `taker_side = 'buy'` 当 `is_buyer_maker = false`

### 11.2 `quote_qty` 不建议在派生时回算

虽然 `quote_qty ≈ price * qty`，但在不同系统/不同精度策略下：

- `price` 与 `qty` 的小数位可能被截断/四舍五入；
- `quote_qty` 可能是上游直接给出的“成交额事实值”。

因此 Raw 层保留 `quote_qty` 是值得的：它减少了“事实不一致”与“精度漂移”风险。

### 11.3 `time` 的时间语义

- `time` 为 epoch ms（UTC 语义），用于排序与窗口化计算；
- 它是**成交发生时间**，不是“你收到消息的时间”（你不记录 `ingested_at`，要接受这一点）。

---

## 12. 类型选型：`NUMERIC(38,12)` 的收益与代价

你当前选型偏向 **确定性与可审计**：

- 训练/回测/复现时，`NUMERIC` 能避免 `float` 带来的不可控舍入误差；
- 对“逐笔 → 聚合”的派生链路更稳健（特别是成交额、VWAP、资金流等指标）。

代价也必须认清：

- `NUMERIC` 写入与聚合 CPU 成本更高，索引体积更大；
- 在全市场、长周期的逐笔全量写入场景下，数据库瓶颈会更早出现。

工程建议（不改 schema 的情况下）：

- 写入侧严禁直接用 `float` 进库：Python 里优先用 `Decimal(str(x))` 或直接从字符串解析。
- 批量写入优先 `COPY` / 批插入，避免逐行 `INSERT` 带来大量事务与索引开销。

---

## 13. 索引、分区与留存（面向规模的“提前声明”）

### 13.1 索引建议的核心逻辑

你最常见的访问模式通常是：

- 给定 `exchange+symbol`，取最近 N 条逐笔；
- 给定 `exchange+symbol`，按时间范围取逐笔窗口；
- 从逐笔派生 1s/1m 聚合（按时间扫描）。

因此索引以 `(exchange, symbol, time)` 为主轴是合理的。

### 13.2 可选增强（按需启用）

- 如果未来存在“大时间范围扫描 + 低选择性过滤”，可考虑 `BRIN(time)`（适合近似按时间写入、且表极大时的范围过滤）。
- 如果你已采用 TimescaleDB，建议把该表作为 hypertable（以 `time` 或生成的 `trade_ts` 作为时间列），并配套：
  - chunk 策略（例如按天/按小时，取决于写入量）
  - 压缩与留存（Raw 层只保留必要窗口，长期分析依赖派生层）

> 注意：如果你坚持不增加 `time_ts`，仍可以以 `time`（BIGINT）做 hypertable，但你需要在工程与查询侧统一“时间单位与边界”，避免 ms/us 混淆。

---

## 14. 典型查询模式（建议固化成可复用 SQL 模板）

### 14.1 最近 N 条逐笔（用于调试与监控）

```sql
SELECT *
FROM crypto.raw_futures_um_trades
WHERE exchange = 'binance'
  AND symbol = 'BTCUSDT'
ORDER BY time DESC, id DESC
LIMIT 100;
```

### 14.2 时间窗口拉取（用于特征计算）

```sql
SELECT
  time,
  price,
  qty,
  quote_qty,
  is_buyer_maker
FROM crypto.raw_futures_um_trades
WHERE exchange = 'binance'
  AND symbol = 'BTCUSDT'
  AND time >= $1
  AND time <  $2
ORDER BY time ASC, id ASC;
```

### 14.3 轻量“方向成交额”聚合（示例）

```sql
SELECT
  (time / 1000) * 1000 AS bucket_ms,
  SUM(CASE WHEN is_buyer_maker THEN quote_qty ELSE 0 END) AS sell_taker_quote,
  SUM(CASE WHEN NOT is_buyer_maker THEN quote_qty ELSE 0 END) AS buy_taker_quote
FROM crypto.raw_futures_um_trades
WHERE exchange = 'binance'
  AND symbol = 'BTCUSDT'
  AND time >= $1
  AND time <  $2
GROUP BY 1
ORDER BY 1;
```

---

## 15. 数据质量与缺口治理（不加 `ingested_at` 也要能自证）

你当前选择不加 `file_id/ingested_at`，并不等于可以放弃质量治理；它只是意味着质量证据要来自“旁路系统”：

- **watermark（高水位）**：按 `exchange+dataset+symbol` 维护最新 `time/id`；
- **gap 检测**：以 `time` 间隔异常为主（带活跃度阈值/容忍窗口）；`id` 只做“单调性/重复”健全性检查，不拿 `id` gap 当缺口依据；
- **补拉策略**：WS 优先，但必须允许“按时间窗口 REST 补齐”（尤其是断线窗口）。

建议最小治理闭环（不改表结构）：

1) 写入后更新 watermark（内存/Redis/小表均可）  
2) 定时任务检测缺口并触发补拉  
3) 补拉仍写同一事实表，依赖 PK 幂等去重  

---

## 16. 演进路线（现实可行 vs 理想完美）

### 16.1 现实可行（保持 8 字段不动）

- 保持当前事实表不变；
- 在工程侧补齐：run/batch 元数据、watermark、gap 检测、补拉重放；
- 从该表派生 1s/1m 聚合表用于长期训练/分析（Raw 控制留存窗口）。

### 16.2 理想完美（当你进入“生产审计/可复现”阶段）

- 额外引入“文件落地区”（Landing Zone）：每行可回溯 `rel_path + checksum`（这更贴合 Binance Vision 的“zip/checksum”产品形态）；
- 事实表与落地区解耦：落地区负责审计与版本链，事实表负责统一查询与派生；
- 针对逐笔规模，考虑：hypertable/分区 + 压缩 + 冷热分层存储（Raw 与派生分治）。

---

## 17. 实时采集链路技术细节（ccxtpro / WS 优先）

### 17.1 事件规范化（Normalizer）

建议在采集器中固定以下映射，避免字段漂移：

- `trade.info.t -> id`
- `trade.info.p -> price`
- `trade.info.q -> qty`
- `price * qty -> quote_qty`（保留 decimal 精度）
- `trade.info.T -> time`（ms）
- `trade.info.m -> is_buyer_maker`
- `trade.info.s -> symbol`（缺失时使用订阅 symbol 回填）
- `exchange -> 'binance'`（常量列）

### 17.2 批写与刷新策略

建议双阈值刷盘/入库：

- 行数阈值：`flush_max_rows`（建议 1000~5000）
- 时间阈值：`flush_interval_seconds`（建议 0.5~2s）

任一阈值触发即执行批写，减少小事务抖动。

### 17.3 断线与重连

- 重试策略：指数退避（1s -> 2s -> 4s ... 上限 60s）
- 连接恢复后继续使用同一幂等键入库（避免重复）
- 退出时先停 WS，再 flush 内存队列（保证“尽量不丢”）

---

## 18. 旁路元数据（不污染事实表的治理设计）

你已经决定不在事实表中放 `file_id/ingested_at`，建议把治理信息放在 sidecar 表。

### 18.1 采集运行表（run 维度）

```sql
-- 注意：按你的约束，不新建 schema，治理表直接建在 crypto 内
CREATE TABLE IF NOT EXISTS crypto.ingest_runs (
  run_id            BIGSERIAL PRIMARY KEY,
  exchange          TEXT NOT NULL,
  dataset           TEXT NOT NULL, -- futures.um.trades
  mode              TEXT NOT NULL CHECK (mode IN ('realtime','backfill','repair')),
  started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at       TIMESTAMPTZ,
  status            TEXT NOT NULL CHECK (status IN ('running','success','failed','partial')),
  error_message     TEXT,
  meta              JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### 18.2 高水位表（symbol 维度）

```sql
CREATE TABLE IF NOT EXISTS crypto.ingest_watermark (
  exchange          TEXT NOT NULL,
  dataset           TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  last_time         BIGINT NOT NULL,   -- epoch ms
  last_id           BIGINT NOT NULL,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (exchange, dataset, symbol)
);
```

### 18.3 缺口记录表（补拉任务输入）

```sql
CREATE TABLE IF NOT EXISTS crypto.ingest_gaps (
  gap_id            BIGSERIAL PRIMARY KEY,
  exchange          TEXT NOT NULL,
  dataset           TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  start_time        BIGINT NOT NULL,
  end_time          BIGINT NOT NULL, -- 约定 end exclusive
  detected_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','repairing','closed','ignored')),
  reason            TEXT,
  run_id            BIGINT REFERENCES crypto.ingest_runs(run_id),
  UNIQUE (exchange, dataset, symbol, start_time, end_time)
);
```

> 这三张表的“人话解释”：
>
> - `ingest_runs`：这次任务干了什么、成功没、失败原因是什么（相当于任务日志）
> - `ingest_watermark`：每个 `symbol` 我已经“写到哪了”（相当于进度条/高水位）
> - `ingest_gaps`：我发现哪里缺了一段，需要补（相当于缺口工单队列）

---

## 19. 数据一致性校验（建议固化为审计 SQL）

### 19.1 `quote_qty` 一致性抽查

```sql
SELECT
  exchange, symbol, id, price, qty, quote_qty,
  ABS(quote_qty - (price * qty)) AS delta
FROM crypto.raw_futures_um_trades
WHERE exchange = 'binance'
  AND symbol = 'BTCUSDT'
  AND ABS(quote_qty - (price * qty)) > 0.00000001
ORDER BY time DESC
LIMIT 100;
```

### 19.2 同键冲突（同 id 不同值）检测

```sql
SELECT
  exchange,
  symbol,
  id,
  COUNT(*) AS cnt
FROM crypto.raw_futures_um_trades
GROUP BY exchange, symbol, id
HAVING COUNT(*) > 1;
```

在当前“主键包含 time”的实现里，这个查询的意义是：

- **正常应为 0**（同一个 trade id 不应该对应多行）
- 若出现 `cnt > 1`：说明同一个 `id` 被写入了多个不同的 `time`（优先按采集/解析异常排查）

### 19.3 单位异常检测（ms/us 混淆）

```sql
SELECT
  MIN(time) AS min_time,
  MAX(time) AS max_time
FROM crypto.raw_futures_um_trades
WHERE exchange = 'binance'
  AND symbol = 'BTCUSDT';
```

UM trades 正常应接近 13 位毫秒时间戳；若出现 16 位，通常是单位混淆。

---

## 20. 性能与容量细节（PostgreSQL/TimescaleDB）

### 20.1 索引策略（当前 8 字段模型）

- 主键：`(exchange, symbol, time, id)`（Timescale hypertable 约束下的物理幂等键）
- 查询索引：`(exchange, symbol, time DESC)`（最近数据与窗口查询）

### 20.2 建议开启的批写参数（应用侧）

- 批大小：1000~5000 行
- 单批事务：1 次提交
- `synchronous_commit`：训练/回测环境可评估 `off`（提升吞吐，接受极小窗口风险）

### 20.3 Timescale 落地建议（本方案已启用）

你不加 `time_ts`，仍然可以直接用 `time BIGINT (epoch ms)` 做 hypertable 分片键；建议参数：

- chunk 粒度：先按天（写入量极高时按小时）
- 压缩策略：30 天后压缩（先满足“永久存储 + 成本可控”）

对应 DDL（已在仓库 schema 中落地）核心形态大致是：

```sql
SELECT create_hypertable('crypto.raw_futures_um_trades', 'time', chunk_time_interval => 86400000, if_not_exists => TRUE);
SELECT set_integer_now_func('crypto.raw_futures_um_trades', 'crypto.unix_now_ms', replace_if_exists => TRUE);
ALTER TABLE crypto.raw_futures_um_trades SET (timescaledb.compress, timescaledb.compress_segmentby = 'exchange,symbol');
SELECT add_compression_policy('crypto.raw_futures_um_trades', 2592000000); -- 30d in ms
```

---

## 21. 面向训练/回测的推荐视图（不改事实表）

```sql
CREATE OR REPLACE VIEW crypto.v_raw_futures_um_trades AS
SELECT
  exchange,
  symbol,
  id,
  to_timestamp(time / 1000.0) AS trade_ts_utc,
  price,
  qty,
  quote_qty,
  is_buyer_maker,
  CASE WHEN is_buyer_maker THEN 'sell' ELSE 'buy' END AS taker_side
FROM crypto.raw_futures_um_trades;
```

作用：

- 统一时间展示与方向语义，减少业务层重复转换；
- 不引入新物理列，保持事实表极简。

---

## 22. 参数基线（可直接落到采集配置）

建议第一版基线：

- `flush_max_rows=2000`
- `flush_interval_seconds=1.0`
- `W(window_seconds)=300`（5min）
- `rest_overlap_multiplier=3`（REST 补拉窗口 = 3*W）
- `queue_maxsize=100000`
- `reconnect_backoff_max=60s`
- `WS 优先 + REST 巡检补齐`（REST 不是主源，主要用于抗抖动/断线窗口修复）

这组参数可作为“先稳定运行，再做容量压测微调”的默认值。

回填文件保留策略（你已确认）：

- ZIP/CSV **不长期保留**：导入完成 + 复核通过后删除（命令行直接用 `--no-files`）。

---

## 23. 数据库边界补充（当前阶段强制）

为避免目标漂移，数据库侧再明确一次边界：

- 只维护 `raw_futures_um_trades` 原子事实表；
- 不创建 `agg_*` 物理表；
- 不执行聚合入库任务；
- 后续聚合统一走你规划的物化视图链路。

这意味着当前数据库优化重点是：**写入吞吐、幂等去重、时间窗口读取稳定性**，而不是聚合性能。

---

## 24. DDL 技术细化（Raw 表）

建议在现有 8 字段基础上补充约束，提升数据可控性：

```sql
ALTER TABLE crypto.raw_futures_um_trades
  ADD CONSTRAINT chk_raw_um_trades_time_ms
  CHECK (time >= 946684800000 AND time < 4102444800000); -- 2000-01-01 ~ 2100-01-01

ALTER TABLE crypto.raw_futures_um_trades
  ADD CONSTRAINT chk_raw_um_trades_price_positive CHECK (price > 0),
  ADD CONSTRAINT chk_raw_um_trades_qty_positive CHECK (qty > 0),
  ADD CONSTRAINT chk_raw_um_trades_quote_qty_nonnegative CHECK (quote_qty >= 0);
```

说明：

- `time` 边界约束用于快速捕获 ms/us 误写；
- 价格与数量正值约束可挡掉脏数据；
- 不依赖应用层“自觉”校验，直接把规则固化到库内。

---

## 25. 批量写入建议（Raw-only）

高吞吐写入建议采用“两阶段”：

1) 先 `COPY` 进入临时表（无索引）  
2) 再 `INSERT ... ON CONFLICT DO NOTHING` 进入事实表

参考 SQL：

```sql
CREATE TEMP TABLE tmp_raw_um_trades (LIKE crypto.raw_futures_um_trades) ON COMMIT DROP;

-- 应用侧 COPY 到 tmp_raw_um_trades

INSERT INTO crypto.raw_futures_um_trades (
  exchange, symbol, id, price, qty, quote_qty, time, is_buyer_maker
)
SELECT
  exchange, symbol, id, price, qty, quote_qty, time, is_buyer_maker
FROM tmp_raw_um_trades
ON CONFLICT (exchange, symbol, time, id) DO NOTHING;
```

这样可以显著减少逐行 `INSERT` 的 WAL/索引写放大。

---

## 26. 索引与维护参数（可落配置）

### 26.1 索引组合（保持极简）

- 主键：`(exchange, symbol, time, id)`  
- 查询索引：`(exchange, symbol, time DESC)`  
- 大表可选：`BRIN(time)`（只在 TB 级范围扫描明显时启用）

### 26.2 autovacuum 建议（高写入表）

```sql
ALTER TABLE crypto.raw_futures_um_trades SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01,
  autovacuum_vacuum_threshold = 5000,
  autovacuum_analyze_threshold = 5000
);
```

目的：降低统计信息滞后，避免查询计划抖动。

### 26.3 fillfactor（可选）

若后续出现更新场景（当前几乎无更新），再考虑：

```sql
ALTER TABLE crypto.raw_futures_um_trades SET (fillfactor = 95);
REINDEX TABLE CONCURRENTLY crypto.raw_futures_um_trades;
```

当前纯追加 + 冲突忽略场景，默认 fillfactor 通常已足够。

---

## 27. 权限模型建议（防止误写）

建议拆分角色：

- `role_ingest_writer`：仅 `INSERT` 到 `crypto.raw_futures_um_trades`
- `role_research_reader`：仅 `SELECT`
- `role_admin_migration`：`DDL/INDEX/MAINTENANCE`

示例：

```sql
REVOKE ALL ON crypto.raw_futures_um_trades FROM PUBLIC;
GRANT SELECT ON crypto.raw_futures_um_trades TO role_research_reader;
GRANT INSERT ON crypto.raw_futures_um_trades TO role_ingest_writer;
```

如果要严格禁止覆盖写，避免给采集器 `UPDATE/DELETE` 权限。

---

## 28. 上线前数据库核对清单（Raw）

- 主键是否生效：`(exchange, symbol, time, id)`  
- 核心索引是否生效：`(exchange, symbol, time DESC)`  
- 约束是否生效：时间单位与正值检查  
- 批写模式是否为“临时表 + 合并入库”  
- 连接池是否限流（避免并发写炸库）  
- `ANALYZE` 是否定期执行  
- 备份策略是否覆盖 `crypto` schema（至少日备份 + WAL）

这份清单通过后，再进入你后续的物化视图聚合阶段。

---

## 29. 实施任务清单（Tasks）

> 范围声明：本阶段只落地 **UM trades raw**，不做 `agg_*` 物理表，不做聚合任务。

### T1. DDL 基线与迁移

- [x] 固化 `crypto.raw_futures_um_trades` 8 字段结构（官方 6 + `exchange/symbol`）
- [x] 主键统一为 `(exchange, symbol, time, id)`（兼容 Timescale 分片约束）
- [x] 开启 hypertable（`time BIGINT(ms)`）+ 30 天压缩策略
- [x] 建立/校正治理表：`crypto.ingest_runs` / `crypto.ingest_watermark` / `crypto.ingest_gaps`

### T2. 实时采集闭环（WS 优先）

- [x] 使用 `ccxtpro.watchTrades` 订阅 UM 成交流
- [x] 字段规范化映射：`t/p/q/T/m/s -> id/price/qty/time/is_buyer_maker/symbol`
- [x] 批写入（行数阈值 + 时间阈值）+ 幂等 `ON CONFLICT DO NOTHING`
- [x] 断线重连 + gap 巡检 + REST 补拉兜底（仅兜底，不替代 WS）

### T3. 历史回填闭环（Vision 权威）

- [x] 支持 `daily/monthly` ZIP 智能选择（完整月优先 monthly）
- [x] 下载后用 `COPY -> 临时表 -> merge` 入库
- [x] 回填冲突策略：`ON CONFLICT (exchange,symbol,time,id) DO UPDATE`（官方覆盖）
- [x] 回填后更新 watermark，并写入 run 状态

### T4. 质量与可观测

- [x] 写入 run 生命周期（running/success/failed/partial）
- [x] 写入 watermark（`last_time/last_id`）
- [x] 记录 gap 队列（`start_time/end_time/reason`）
- [x] 固化 3 条审计 SQL：同键冲突、时间单位异常、`quote_qty` 一致性

### T5. CLI 与工程交付

- [x] `python -m src collect` 支持实时参数（flush/window/gap）
- [x] `python -m src backfill` 支持日期区间与 monthly 优先开关
- [x] 补齐最小单元测试（字段映射、路径、回填计划）
- [x] 本地跑通 `py_compile + pytest`
