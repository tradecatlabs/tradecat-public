# Crypto 逐笔（trades）事实表：业内成熟版全局技术设计（New Structure）

> 本文目标：给出“专业量化团队可长期运行”的逐笔数据落库方案（**最终形态**），覆盖：表结构/字段类型/分片与压缩/幂等与冲突裁决/审计追溯/迁移与回滚/验收口径。  
> 适用范围：TradeCat 当前主线 `Binance Vision -> futures/um/trades`；其他交易所/市场按同一框架扩展。  
> 重要约束（来自你当前明确要求）：  
> - **官方目录结构 = 数据契约**；字段必须对齐官方 CSV（缺字段禁止入库）。  
> - **事实表保持 Raw/Atomic**：只收第一性数据；派生层（agg/klines/特征）后置。  
> - **实时优先 WS**：实时采集必须优先 `ccxtpro` WebSocket；无 WS 才允许 REST。  
> - **事实表不放过程字段**：不加 `file_id/ingested_at/time_ts`；时间用 `time BIGINT(ms)`，展示时再转换。  
> - **不保留 v1/v2 并存**：升级结构用“迁移 + rename swap”，最终只保留一个正式表名。  

---

## 1. 一句话结论（你要的“最成熟方案”）

业内成熟做法不是“把字段堆进一张表”，而是：

1) **事实表主键要短 + 固定宽度**（用整型维度键 `venue_id/instrument_id`，不用 `TEXT` 做主键）。  
2) **数值列用固定宽度类型**（默认 `DOUBLE PRECISION`；极致精确对账可选 scaled-int）。  
3) **时间用整数 epoch(ms) 做分片轴**（Timescale integer hypertable），避免写入端做 `timestamptz` 解析开销。  
4) **可追溯靠旁路审计表**（`storage.*`），不是把 `file_id` 强塞进事实表。  
5) **最终一致性靠“冲突裁决策略”**（实时只追加，官方回填可覆盖修正）。  

---

## 2. 系统分层（全局视角）

```text
----------------+-------------------------------------------------------+
| schema         | 职责                                                  |
|----------------+-------------------------------------------------------|
| crypto         | 原子事实表 + 采集治理旁路（runs/watermark/gaps）      |
| storage        | 文件/批次/错误/版本链审计（证据链，可复现）            |
| core           | 维表（venue/instrument/symbol_map），解决一致命名/降成本 |
----------------+-------------------------------------------------------+
```

仓库内 DDL 真相源：

- `libs/database/db/schema/008_multi_market_core_and_storage.sql`
- `libs/database/db/schema/009_crypto_binance_vision_landing.sql`（会被本方案的“最终 DDL”替换其中的 trades 部分）
- `libs/database/db/schema/013_core_symbol_map_hardening.sql`（symbol_map 必须写死的硬约束：active 唯一性/窗口自洽/窗口不重叠）
- `libs/database/db/schema/016_crypto_trades_readable_views.sql`（trades 可读视图：时间戳转换 + as-of 映射）
- `libs/database/db/schema/019_crypto_raw_trades_sanity_checks.sql`（raw trades 最小 sanity CHECK：默认 NOT VALID，上线护栏）
- `libs/database/db/schema/012_crypto_ingest_governance.sql`

相关 runbook / 索引：

- `assets/docs/analysis/crypto_raw_trades_hardening_runbook.md`（约束硬化、历史一致性、`--force-update` 权限隔离）
- `assets/docs/analysis/INDEX.md`（assets/docs/analysis 单点真相入口）

---

## 3. 数据契约（Binance Vision UM trades）

### 3.1 官方目录（权威历史源）

- daily ZIP：`data/futures/um/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.zip`  
- monthly ZIP：`data/futures/um/monthly/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM.zip`  
- checksum：同名追加 `.CHECKSUM`（`<sha256><two spaces><filename>`）  

### 3.2 官方 CSV 字段（必须全量对齐）

UM trades header：

- `id`：trade id（整数）  
- `price`：成交价  
- `qty`：成交量  
- `quote_qty`：成交额（通常 = price * qty）  
- `time`：成交时间（epoch ms）  
- `is_buyer_maker`：买方是否为 maker（bool）  

补齐规则（允许，但必须写死且可测试）：

- 实时侧缺 `quote_qty`：允许 `quote_qty = price * qty` 补齐（语义对齐官方）。  

---

## 4. 事实表（最终结构：专业版）

> 关键原则：**事实表的主键必须短**，否则索引体积/写放大会把系统拖死（你现在遇到的“索引体积接近数据体积”就是典型症状）。  

### 4.1 维度键（替代 TEXT 作为主键）

- `venue_id`：交易所/场所（例：`binance_futures_um` / `binance_spot`）  
  - 来源：`core.venue(venue_code='<exchange>_<product>')`（例：`binance_futures_um`）  
- `instrument_id`：统一金融工具 ID（例：BTCUSDT 永续合约对应 1 个 instrument）  
  - 来源：`core.instrument` + `core.symbol_map(venue_id, symbol->instrument_id)`  

补充（你朋友指出的系统性 P0，必须提前写死）：

- **产品维度必须纳入键空间**：同一交易所的 spot / futures_um / futures_cm / option 会共享 `BTCUSDT` 这类同名 symbol。  
  - 最小方案（不改 schema）：把 product 折叠进 `core.venue.venue_code`，例如 `binance_spot / binance_futures_cm / binance_option`。  
  - 兼容性：若历史运行库曾把 `futures_um` 落在 `venue_code=binance` 下，需先做一次性迁移：`core.venue: binance -> binance_futures_um`（保持 `venue_id` 不变），脚本见 `libs/database/db/schema/018_core_binance_venue_code_futures_um.sql`；再切换采集代码。

> 对人类可读的 `exchange/symbol`：不放进事实表主键；用 view/维表 join 恢复。  

### 4.2 数值类型选型（两档）

#### A 档（默认推荐：性能/体积优先）

- `price/qty/quote_qty`：`DOUBLE PRECISION`

适合场景：

- 训练/回测/特征工程/统计类分析（吞吐第一）  

#### B 档（精确对账优先：更复杂）

- 使用 scaled-int：  
  - `price_i BIGINT, qty_i BIGINT, quote_qty_i BIGINT`  
  - scale（小数位）固定在 instrument 维表或 meta 中（统一规则）  

适合场景：

- 需要“逐位小数完全精确”对账（例如财务级别对账）  

> 你当前阶段目标是“高频数据底盘 + 训练/回测”，A 档是业内更常见的默认。  

### 4.3 最终 DDL（A 档，推荐）

> 注意：这里的表名仍然是 `crypto.raw_futures_um_trades`，因为你要求“不保留 v2 并存”。迁移期用 `*_new` 临时表，最终 rename swap 回正式名。

```sql
-- 事实表（最终形态）：固定宽度 + 短主键
CREATE TABLE crypto.raw_futures_um_trades (
  -- 与现有 core.* 维表保持类型一致（core.venue/core.instrument 都是 BIGSERIAL=BIGINT）
  -- 说明：BIGINT 仍然比 (exchange,symbol) TEXT 主键省一个数量级的索引体积；
  -- 如果你未来真要“更短”，再额外引入 compact key 映射表（额外工程复杂度）。
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

-- integer hypertable 的 now()（用于压缩/保留等 policy job）
CREATE OR REPLACE FUNCTION crypto.unix_now_ms() RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
  SELECT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
$$;

-- Timescale：整数时间轴 hypertable（ms）
SELECT create_hypertable(
  'crypto.raw_futures_um_trades',
  'time',
  chunk_time_interval => 86400000, -- 1 day (ms)
  create_default_indexes => FALSE,
  if_not_exists => TRUE
);

-- 仅保留主键索引（禁止默认 time 索引，降低写入放大/索引体积）
DROP INDEX IF EXISTS crypto.raw_futures_um_trades_time_idx;
SELECT set_integer_now_func('crypto.raw_futures_um_trades', 'crypto.unix_now_ms', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_futures_um_trades
  SET (timescaledb.compress = TRUE,
       timescaledb.compress_segmentby = 'venue_id,instrument_id',
       timescaledb.compress_orderby = 'time,id');

DO $$
BEGIN
  -- 30 days = 30 * 86400000(ms)
  PERFORM add_compression_policy('crypto.raw_futures_um_trades', 2592000000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;
```

---

## 5. “新旧变化”映射（落地迁移用）

> 旧表（现状）主键：`(exchange TEXT, symbol TEXT, time BIGINT, id BIGINT)`  
> 新表（目标）主键：`(venue_id, instrument_id, time, id)`  

```text
+-------------------+----------------------------+--------------------------+
| 旧列               | 新列                        | 迁移/来源                 |
+-------------------+----------------------------+--------------------------+
| exchange TEXT      | venue_id BIGINT            | core.venue(venue_code)   |
| symbol TEXT        | instrument_id BIGINT       | core.symbol_map 映射      |
| id BIGINT          | id BIGINT                  | 原样                       |
| price NUMERIC      | price DOUBLE PRECISION     | cast，或 scaled-int 方案   |
| qty NUMERIC        | qty DOUBLE PRECISION       | cast                       |
| quote_qty NUMERIC  | quote_qty DOUBLE PRECISION | cast                       |
| time BIGINT(ms)    | time BIGINT(ms)            | 原样                       |
| is_buyer_maker     | is_buyer_maker BOOLEAN     | 原样                       |
+-------------------+----------------------------+--------------------------+
```

---

## 6. 可读性层（不污染事实表）

### 6.1 readable view（给人查）

```sql
CREATE VIEW crypto.raw_futures_um_trades_readable AS
SELECT
  v.venue_code AS exchange,
  sm.symbol    AS symbol, -- 展示“当时”symbol（按 effective_from/effective_to 选一条）
  t.venue_id,
  t.instrument_id,
  t.id,
  t.price,
  t.qty,
  t.quote_qty,
  t.time,
  ts.time_ts_utc,
  t.is_buyer_maker
FROM crypto.raw_futures_um_trades t
-- 只用于展示/联结：把 epoch(ms) 转成 timestamptz（物理事实仍是 time BIGINT）
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

关于 `symbol_map` 的“行数放大”风险（必须明确）：

- 上面这个 view 选择的是“**当时**的 symbol”（按 `effective_from/effective_to` 选一条），并且用 `ORDER BY effective_from DESC LIMIT 1` 强制只取 1 行，避免一对多 join 把结果行数放大。  
- 但这隐含一个数据合同：**同一时刻**对同一 `(venue_id,instrument_id)` 不应该存在多条“同时有效”的映射（有效区间不重叠）。  
- 如果你更想展示“**当前** symbol”，可以改回 `effective_to IS NULL` 的 join，但必须在 `core.symbol_map` 上保证“当前映射唯一”（至少要做到 `(venue_id,instrument_id)` 只有 1 条 `effective_to IS NULL`）。  

### 6.2 “UTC+8 显示但不改物理数据”

两种业内常用方式（二选一）：

1) **客户端会话时区**：`SET TIME ZONE 'Asia/Shanghai';`（对 `timestamptz` 展示生效）  
2) **view 中显式转换**：`time_ts_utc AT TIME ZONE 'Asia/Shanghai'` 生成展示列  

你的事实表 `time` 是 `BIGINT`，本质不受时区影响；时区只影响“把整数转成时间戳后的显示”。  

---

## 7. 写入策略（幂等 + 冲突裁决 = 成熟系统关键）

### 7.1 幂等键

幂等去重永远基于事实表主键：

- 新结构：`(venue_id, instrument_id, time, id)`

### 7.2 冲突裁决（谁为准）

- **实时（WS）**：`ON CONFLICT DO NOTHING`  
  - 目的：抗重连/抗重复投递，避免 UPDATE 造成锁与膨胀。  
- **回填（官方 ZIP）**：`ON CONFLICT DO UPDATE`（受控更新）  
  - 目的：官方是权威源，允许修正实时先写的同键行，最终一致性靠回填收敛。  

> 这不是“要不要去重”的问题；去重由主键保证。这里决定的是：**重复键出现时，到底“跳过”还是“覆盖修正”。**  

### 7.3 压缩窗口硬约束（会长期咬人，必须写死）

> 结论：**回填/修复的 UPDATE 必须发生在压缩生效前**；否则会触发“解压/重压”或直接写入失败，成本极高。

硬规则（建议写进运行策略/任务门禁）：

- **初次全量回填阶段**：不要让后台压缩 job 抢跑。做法二选一：
  - 先不执行 `add_compression_policy(...)`，等全量回填完成后再开启；或
  - 回填期临时 `remove_compression_policy(...)`，完成后再加回。
- **稳态运行阶段**：
  - realtime：只做 `DO NOTHING`（只追加），天然不需要更新历史。
  - backfill/repair：只允许在“热窗口（未压缩）”内做 `DO UPDATE`；超出热窗口默认降级为 `DO NOTHING` 或人工流程。
- **极少数必须更新已压缩 chunk 的情况**（异常路径）：显式 `decompress_chunk → UPDATE → compress_chunk`，并记录审计批次与原因。

---

## 8. 审计追溯（storage.*）：成熟系统的证据链

你必须长期坚持的最小审计集合：

- `storage.files`：每个 zip/csv 的 `rel_path/sha256/size/row_count/min/max/meta`  
- `storage.file_revisions`：同路径 checksum 变化（上游替换）  
- `storage.import_batches`：每次回填/repair 批次  
- `storage.import_errors`：结构化错误（checksum_missing/mismatch/parse_failed/ingest_failed…）  

为什么不把 `file_id` 放进事实表？

- 放进去会让 PK 变大、索引更大、写放大更严重；  
- 逐笔是海量事实，追溯用“文件级证据链 + 批次日志 + 可重建能力”更成熟、更省。  

---

## 9. 治理闭环（crypto.ingest_*）：能自动补、能证明补过

- `crypto.ingest_runs`：每次运行有 `run_id/status/meta`，可回溯  
- `crypto.ingest_watermark`：每个 `(exchange,dataset,symbol)` 的高水位（`last_time/last_id`；或成熟后升级为 ids）  
- `crypto.ingest_gaps`：缺口工单（`open -> repairing -> closed/ignored`），repair 并发安全消费（`SKIP LOCKED`）  

---

## 10. 迁移协议（不保留 v2 的正确落地方式）

> 目标：从旧表迁移到新结构，并最终仍叫 `crypto.raw_futures_um_trades`。

1) **准备维表映射**：确保 `core.venue/binance` 与 `core.symbol_map(binance,BTCUSDT->instrument_id)` 完整。  
2) **创建新表**：`crypto.raw_futures_um_trades_new`（按第 4 节 DDL）。  
3) **迁移数据**：旧表 join 映射写入新表（批次化，避免长事务）。  
4) **对账门禁**：按时间窗抽样对比 count、min/max time、重复率（误差=0）。  
5) **停写入窗口**：暂停 realtime/backfill 写入（短窗口）。  
6) **rename swap**：  
   - 旧表 → `crypto.raw_futures_um_trades_old`  
   - 新表 → `crypto.raw_futures_um_trades`（正式名）  
7) **回滚路径**：任何异常直接 swap 回旧表（表名换回即可），写入链路不必改太多。  

---

## 11. 验收口径（人话版）

- **重复跑不重复**：同一个官方文件重复导入，事实表行数不增长（只会覆盖修正或跳过）。  
- **能证明没缺没多**：任意一天/任意文件，都能对上 `sha256/row_count/min/max` 与事实表窗口一致。  
- **断了能自动补**：gap 生成后 repair 能补齐并把 gap 关闭。  
- **查得明白**：人类查询用 readable view，不牺牲事实表成本。  

### 11.1 “窗口合同”（没有 file_id 的前提下，必须靠它对账）

> 因为事实表不存 `file_id`，所以“单文件对账”只能通过**官方文件 → 时间窗口**来建立可重复的映射关系；这必须写成硬合同。

- **daily 文件窗口（UTC）**：`[YYYY-MM-DD 00:00:00Z, YYYY-MM-(DD+1) 00:00:00Z)`（start 含、end 不含）  
- **monthly 文件窗口（UTC）**：`[YYYY-MM-01 00:00:00Z, next_month 00:00:00Z)`（start 含、end 不含）  
- **月包与日包重叠**：
  - 若选择“月优先”（推荐）：同一月份以 monthly 为权威源，daily 仅在该月 monthly 缺失时补齐。
  - 若两者都导入：依赖主键幂等去重，最终窗口内行数应收敛到“权威源”那份文件的 `row_count`。

---

## 12. 你现在要做的决策（只剩 1 个）

数值类型选型二选一：

- 选 **A 档（DOUBLE）**：更省、更快、更像业内默认（推荐）。  
- 选 **B 档（scaled-int）**：更精确，但要先定统一 scale 规则并承担工程复杂度。  

> 你拍板后，我会把 DDL、迁移脚本步骤、以及采集写入的字段映射统一对齐到这一档。  
