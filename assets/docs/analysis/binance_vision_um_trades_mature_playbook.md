# Binance Vision `futures/um/trades`：从 0 到 1 的业内成熟落地手册（不保留 v2 版本）

> 本文是“整套方案文档”（设计→落地→验收→运维），以 **Binance Vision UM trades** 作为模板；其他数据集按同一框架套用即可。
>
> 关键前提（你的硬约束）：
> - 官方目录结构=数据契约；字段必须对齐官方 CSV（缺字段禁止入库）。
> - 事实表保持 Raw/Atomic；派生层（agg/klines/指标）后置、可重建。
> - 实时侧必须优先 `ccxtpro` WS；无 WS 才 REST。
> - **不保留“v1/v2 双版本并存”**：需要升级时，用“迁移+切换”把旧形态替换成新形态（保留回滚路径）。

---

## 0. 术语与目标

### 0.1 术语

- **事实表（Fact / Raw）**：只存不可再还原的原子事实（本例：逐笔成交 trades）。
- **权威源（Authoritative Source）**：
  - 历史：`data.binance.vision` 的 ZIP/CSV（带 `.CHECKSUM`）。
  - 实时：交易所 WS 推送（ccxtpro watchTrades），必要时用 REST overlap 兜底。
- **审计（Audit）**：能回答“某条/某天数据来自哪个官方 rel_path、哪个 sha256、导入时发生了什么错误”。
- **治理闭环（Governance Loop）**：实时发现 gap → 结构化记录 → repair 自动补齐 → 关闭工单（open→closed）。

### 0.2 成熟系统必须回答的 10 个问题

1) 我今天的数据是否完整？缺了多少？  
2) 缺口在哪里？为什么缺？能自动修复吗？  
3) 我写入的这份数据能证明“没被代理/缓存污染”吗？  
4) 同一路径文件被上游替换，我能发现并留证据链吗？  
5) 回填和实时冲突时，谁为准？是否允许 UPDATE？  
6) 系统崩溃/重启后，会不会重复写入/漏写？  
7) 资源吃满（内存/磁盘/DB）时会怎么退化？会不会 OOM？  
8) “数据可用于训练/回测”的导出产物怎么做？能否重复生成？  
9) 运维上怎么看健康度（lag/吞吐/错误率/缺口数）？  
10) 我能把整个库从权威源重建出来吗？多久？成本多少？

---

## 1. 数据契约（官方）

### 1.1 官方目录与文件名

- daily ZIP：
  - `data/futures/um/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.zip`
- monthly ZIP：
  - `data/futures/um/monthly/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM.zip`
- checksum：
  - 同名追加 `.CHECKSUM`（内容格式：`<sha256><two spaces><filename>`）

### 1.2 CSV 字段（必须全量对齐）

UM trades CSV header：

- `id`：trade id（BIGINT）
- `price`：成交价（十进制）
- `qty`：成交量（十进制）
- `quote_qty`：成交额（十进制，通常=price*qty）
- `time`：成交时间（epoch ms）
- `is_buyer_maker`：买方是否为 maker（bool）

**注意**：实时侧如果拿到的 trade 没有 `quote_qty`，允许按 `price*qty` 计算补齐（语义一致）。

---

## 2. 目录结构（官方=代码契约）

### 2.1 代码目录（dataset cards）

- 实时采集卡片（realtime）：`services/ingestion/binance-vision-service/src/collectors/crypto/data/**`
- 历史下载/回填卡片（download/backfill）：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/**`
- 治理闭环（repair）：`services/ingestion/binance-vision-service/src/collectors/crypto/repair/**`

### 2.2 运行时落盘目录（禁止进 Git）

- 实时 CSV：`services/ingestion/binance-vision-service/data/**`
- 历史 ZIP：`services/ingestion/binance-vision-service/data_download/**`
- 临时与状态：`services/ingestion/binance-vision-service/run/**`

---

## 3. 数据库总览（成熟的“分层职责”）

```text
-----------------------------+----------------------------------------------+
| schema                      | 职责                                         |
|-----------------------------+----------------------------------------------|
| crypto                       | 原子事实表 + 旁路治理表（runs/watermark/gaps）|
| storage                      | 文件/批次/错误/版本链审计（可追溯证据链）     |
| core                         | 维表（交易所/标的/映射），支撑字典化与一致命名 |
-----------------------------+----------------------------------------------+
```

你现在已经在仓库里具备这些 DDL（真相源）：

- `assets/database/db/schema/008_multi_market_core_and_storage.sql`
- `assets/database/db/schema/009_crypto_binance_vision_landing.sql`
- `assets/database/db/schema/013_core_symbol_map_hardening.sql`（symbol_map 必须写死的硬约束：active 唯一性/窗口自洽/窗口不重叠）
- `assets/database/db/schema/016_crypto_trades_readable_views.sql`（trades 可读视图：时间戳转换 + as-of 映射）
- `assets/database/db/schema/018_core_binance_venue_code_futures_um.sql`（兼容性迁移：若历史运行库把 futures_um 写在 `venue_code=binance` 下，需先改名为 `binance_futures_um` 且保持 `venue_id` 不变）
- `assets/database/db/schema/012_crypto_ingest_governance.sql`
- `assets/database/db/schema/019_crypto_raw_trades_sanity_checks.sql`（raw trades 最小 sanity CHECK：默认 NOT VALID，上线护栏）

相关 runbook / 索引：

- `docs/analysis/crypto_raw_trades_hardening_runbook.md`（约束硬化、历史一致性、`--force-update` 权限隔离）
- `docs/analysis/INDEX.md`（docs/analysis 单点真相入口）

---

## 4. 事实表设计（重构目标形态：直接替换，不保留 v2）

> 核心理念：**事实表的主键要短、固定宽度**；人类可读性用 view/维表解决，不要用 TEXT 主键付出索引成本。

### 4.1 推荐物理列类型（两档）

#### A 档（默认推荐：训练/回测友好，性能优先）

- `price/qty/quote_qty`：`DOUBLE PRECISION`（固定 8B）
- 优点：体积小、扫描快、压缩效果好
- 缺点：极端情况下无法做到“逐位小数完全精确对账”（但对 ML/回测通常足够）

#### B 档（精确对账优先：工程复杂度更高）

- 使用 `scaled-int`：
  - `price_i BIGINT`, `qty_i BIGINT`, `quote_qty_i BIGINT`
  - `price_scale SMALLINT`, `qty_scale SMALLINT`（通常存到 instrument 维表即可）
- 优点：固定宽度 + 精确
- 缺点：需要明确定义 scale（按 instrument），并处理乘法溢出与转换

> 你目前实时侧已经用 `Decimal(str(...))` 解析（准确），这意味着你有能力做 B 档；但 B 档的“统一 scale 规则”必须先定。

### 4.2 主键与分片（不保留 v2 的含义）

你要求“不要 v2 版本”，正确的做法是：

- 允许在迁移期临时创建 `*_new` 表
- 数据校验完成后 **替换**（rename swap）到同一个最终表名
- 迁移完成后只保留一个事实表：`crypto.raw_futures_um_trades`

### 4.3 目标 DDL（示例：A 档，推荐）

> 下面是“目标形态”，用于指导重构；实际落地前先备份与演练（见第 12 节迁移协议）。

```sql
-- 核心：不用 TEXT 做主键；用整型维度键
CREATE TABLE crypto.raw_futures_um_trades (
  -- 与现有 core.* 维表保持类型一致（core.venue/core.instrument 都是 BIGSERIAL=BIGINT）
  venue_id        BIGINT NOT NULL,
  instrument_id   BIGINT NOT NULL,
  id              BIGINT   NOT NULL,
  price           DOUBLE PRECISION NOT NULL,
  qty             DOUBLE PRECISION NOT NULL,
  quote_qty       DOUBLE PRECISION NOT NULL,
  time            BIGINT   NOT NULL, -- epoch ms
  is_buyer_maker  BOOLEAN  NOT NULL,
  PRIMARY KEY (venue_id, instrument_id, time, id)
);

CREATE OR REPLACE FUNCTION crypto.unix_now_ms() RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
  SELECT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
$$;

SELECT create_hypertable(
  'crypto.raw_futures_um_trades',
  'time',
  chunk_time_interval => 86400000, -- 1 day in ms
  create_default_indexes => FALSE,
  if_not_exists => TRUE
);

DROP INDEX IF EXISTS crypto.raw_futures_um_trades_time_idx;
SELECT set_integer_now_func('crypto.raw_futures_um_trades', 'crypto.unix_now_ms', replace_if_exists => TRUE);
ALTER TABLE crypto.raw_futures_um_trades
  SET (timescaledb.compress = TRUE,
       timescaledb.compress_segmentby = 'venue_id,instrument_id',
       timescaledb.compress_orderby = 'time,id');

DO $$
BEGIN
  PERFORM add_compression_policy('crypto.raw_futures_um_trades', 2592000000); -- 30d in ms
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;
```

### 4.4 可读性（不给主键加 TEXT 的前提下仍可读）

提供只读 view（示意）：

```sql
CREATE VIEW crypto.raw_futures_um_trades_readable AS
SELECT
  v.venue_code AS exchange,
  sm.symbol    AS symbol, -- 展示“当时”symbol（按 effective_from/effective_to 选一条）
  t.*,
  ts.time_ts_utc
FROM crypto.raw_futures_um_trades t
CROSS JOIN LATERAL (SELECT to_timestamp(t.time / 1000.0) AS time_ts_utc) ts
JOIN core.venue v ON v.venue_id = t.venue_id
LEFT JOIN LATERAL (
  SELECT sm.symbol
  FROM core.symbol_map sm
  WHERE sm.venue_id = t.venue_id
    AND sm.instrument_id = t.instrument_id
    AND sm.effective_from <= ts.time_ts_utc
    AND (sm.effective_to IS NULL OR ts.time_ts_utc < sm.effective_to)
  ORDER BY sm.effective_from DESC
  LIMIT 1
) sm ON TRUE;
```

---

## 5. 审计层（storage.*）：把“证据链”变成结构化数据

你已经落地的成熟做法（必须长期坚持）：

- 每个 ZIP（daily/monthly）：
  - 下载 `.CHECKSUM`，校验 sha256
  - 写入 `storage.files`：`rel_path/checksum_sha256/size_bytes/row_count/min_event_ts/max_event_ts/meta`
  - 如果同路径 checksum 变化：写 `storage.file_revisions`
- 每次导入批次：
  - `storage.import_batches` 记录批次元信息（dataset/symbols/date range/参数）
  - `storage.import_errors` 记录结构化错误（download_failed/checksum_mismatch/ingest_failed…）

> 这部分是“成熟系统”的底盘：没有它，你就无法证明你拿到的数据可信。

---

## 6. 治理闭环（crypto.ingest_*）：runs / watermark / gaps

### 6.1 运行生命周期（ingest_runs）

- 每次 collect/backfill/repair 都产生 `run_id`
- `status` 必须闭合：`running -> success/partial/failed`

### 6.2 高水位（ingest_watermark）

对每个 `(exchange,dataset,symbol)`（或重构后用 ids）记录：

- `last_time`：最大 event time
- `last_id`：最大 trade id（同时间戳高频时用于强去重与补拉）

### 6.3 缺口队列（ingest_gaps）

- 实时侧发现 stale/断线/延迟：写 gap（`open`）
- repair worker 并发消费：
  - `open -> repairing`（SKIP LOCKED）
  - 补齐成功：`closed`
  - 暂时不可修（例如 Vision 未发布当天文件）：`open`（等待下次）

---

## 7. 实时采集（WS 优先）端到端流程

### 7.1 数据流（简图）

```text
---------+     WS      +--------------------+   buffer   +------------------+
 Binance | ----------> | ccxtpro.watchTrades| ---------> | CSV/DB flush loop |
---------+             +--------------------+            +------------------+
                                  |                               |
                                  | gap detect (stale)            | upsert watermark
                                  v                               v
                           crypto.ingest_gaps                crypto.ingest_watermark
                                  |
                                  v
                             REST overlap (兜底)
```

### 7.2 关键工程点（成熟做法）

- **字段完备**：从 `trade.info` 取 `t/p/q/T/m/s`；缺 `quote_qty` 用 `price*qty` 补齐
- **幂等写入**：
  - DB：主键冲突 `DO NOTHING`（实时不做 UPDATE，避免放大）
  - CSV：按官方字段顺序追加
- **资源与溢出**：
  - queue/buffer 必须有界
  - 写入变慢要能背压或降级（例如暂停 DB，只落盘）
- **断线重连**：
  - 指数退避 + 上限（例如 60s）
- **gap 发现**：
  - 超阈值未收到成交 → 写 gap + REST overlap 补拉

---

## 8. 历史回填（Vision ZIP）端到端流程

### 8.1 智能边界（业内常规）

- 整月优先 monthly
- 边界月/当前月按日
- monthly 404 自动降级 daily（不能失败就停）

### 8.2 完整性与审计（成熟做法）

- `.CHECKSUM` 强校验（默认严格；逃生阀必须显式打开）
- 导入写入 `storage.*`（文件、批次、错误、版本链）
- DB 导入：`COPY -> temp -> INSERT/UPSERT`

---

## 9. repair：缺口修复闭环（必须可并发）

### 9.1 并发安全认领（关键）

- SQL：`FOR UPDATE SKIP LOCKED`
- 语义：多进程同时跑 repair 也不会重复处理同一个 gap

### 9.2 时间窗→UTC 日期范围

约定：

- gap 的 `end_time` 是 **end exclusive**
- 转 date 时需要用 `end_time-1ms` 防止跨天误判

---

## 10. 质量与对账（DQ）

成熟系统不是“写入成功就算成功”，而是：

- 文件级证据：`sha256/row_count/min_ts/max_ts`
- 表级对账：窗口内 `COUNT(*) >= file_rows`（回填）/ 去重率异常报警
- 缺口统计：`open gaps` 长期堆积必须报警

---

## 11. 资源占用、回收、溢出止损（你点名要的）

### 11.1 内存

- buffer/queue 有界（maxsize + flush）
- queue 满：必须明确策略（阻塞背压 / 丢弃并记 gap / 落盘缓冲）

### 11.2 磁盘

- `data/ data_download/ run/`：
  - 保留策略（按天/按大小）
  - 磁盘满：止损（暂停下载/暂停落盘/只写 DB 或反之）

### 11.3 DB 压力

- 写入延迟升高：
  - 降低并发/增大 flush 间隔/切换为仅落盘
  - 结构化记录到 run meta（否则“故障不可复盘”）

---

## 12. “不要 v2”：直接重构的迁移协议（从旧表到新表）

> 这部分是你要的“直接重构”：不是并存两套表，而是用安全迁移替换旧形态。

### 12.1 迁移前硬门禁（必须）

1) 备份（至少逻辑备份/或快照）  
2) 确认写入暂停（避免迁移过程中实时还在写）  
3) 预演迁移窗口（至少 1 个 symbol、1 天）  

### 12.2 推荐迁移步骤（通用模板）

1) 创建/补齐 `core.*` 维表（venue/instrument/symbol_map）  
   - Binance：产品维度必须纳入 `core.venue.venue_code` 键空间（UM=`binance_futures_um`）；若旧库仍为 `binance`，先应用 `018_core_binance_venue_code_futures_um.sql`  
2) 创建新表 `crypto.raw_futures_um_trades_new`（目标 DDL）  
3) 从旧表迁移数据：
   - 把旧表的 `exchange/symbol` 映射到 `(venue_id,instrument_id)`
   - 迁移 price/qty/quote_qty（按你选的 A 档/B 档转换）
4) 校验：
   - 总行数、抽样窗口 COUNT、一致性检查
5) swap：
   - `ALTER TABLE ... RENAME`（旧→_old，新→正式名）
6) 修改采集写入代码（写入新列）并上线  
7) 观察期结束后清理旧表（或保留一段时间做回滚）

### 12.3 回滚策略（必须写清楚）

- 任何异常：立刻切回旧表名 + 旧写入代码
- repair/backfill 仍可重跑（幂等键保证）

---

## 13. 从 0 到 1 的最小落地步骤（可执行）

1) 启动数据库并确认可连接（本机示例：15432）  
2) 应用 DDL（core/storage/crypto raw + governance）  
3) 先跑 1 天回填（BTCUSDT）并验证：
   - `storage.files` 有记录且 checksum 非空
   - `storage.import_errors` 为 0
   - `crypto.raw_futures_um_trades` 窗口内 count > 0
4) 启动实时采集（WS）跑 10 分钟：
   - watermark 单调递增
   - 人为断网制造 gap，检查 `ingest_gaps` 产生 open
5) 跑 repair：
   - open->repairing->closed

---

## 14. 你接下来最应该做的 3 件事（按收益排序）

1) **真实库里跑一次 repair 验收**（证明闭环真的闭合）  
2) **决定事实表数值类型选 A 还是 B**（double 还是 scaled-int）  
3) **把“溢出止损策略”写成硬门禁**（否则一旦压力上来会 OOM/卡死）  
