# Binance Vision UM Trades：业内成熟做法差距复核（持久化沉淀）

> 目的：把“我们现在有什么 / 离业内成熟 tick-store 还差什么 / 下一步最值钱的升级是什么”固化成一份长期可复用的工程笔记。  
> 范围：仅针对 **Binance Vision → futures/um/trades**（Raw/原子逐笔成交）。
>
> 重要更新（2026-02-15）：事实表已升级为“业内成熟结构”（`venue_id/instrument_id + DOUBLE`），旧的 `exchange/symbol TEXT + NUMERIC` 形态已废弃；若你的本机库仍是旧表，需要按迁移协议执行 rename swap。

---

## 0. 当前状态快照（以代码与库为准）

# 数据集契约（官方）
- 官网路径：`data/futures/um/{daily|monthly}/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-....zip`
- CSV header：`id,price,qty,quote_qty,time,is_buyer_maker`
- 时间单位：`time` 为 `epoch(ms)`

# 采集实现（本仓库）
- 实时（WS 优先）：`services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/um/trades.py`
  - `ccxtpro.watchTrades` 为主；若 stale 触发巡检，则用 `fetch_trades` 做 overlap 补拉兜底
  - 落盘路径：`services/ingestion/binance-vision-service/data/**`（运行时目录，git ignore）
- 回填（Vision ZIP）：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/trades.py`
  - “月+日智能边界”：整月优先 monthly；边界月/当月按日；月度 404 自动降级日度
  - **完整性**：强制下载并校验 `.CHECKSUM/sha256`；不一致视为失败并重试（可用 `--allow-no-checksum` 逃生阀）
  - **审计**：导入过程写入 `storage.files / storage.file_revisions / storage.import_batches / storage.import_errors`
  - 入库路径：先 `COPY` 到 temp，再 `INSERT ... ON CONFLICT ... DO UPDATE` 写入事实表
 - 修复（gap repair）：`services/ingestion/binance-vision-service/src/collectors/crypto/repair/futures/um/trades.py`
   - 消费 `crypto.ingest_gaps(status='open')` → 触发权威回填 → 成功则关闭 gap（open->repairing->closed）

# 落库（事实表：成熟结构）
- 库/Schema：`market_data.crypto`
- 表：`crypto.raw_futures_um_trades`
- 字段（8 个）：官方 6 个 + 维度键 2 个
  - 官方：`id,price,qty,quote_qty,time,is_buyer_maker`
  - 维度：`venue_id,instrument_id`（通过 `core.venue/core.symbol_map` 把 exchange/symbol 字典化）
- 幂等键（主键）：`PRIMARY KEY(venue_id, instrument_id, time, id)`
- Timescale：integer hypertable（time=ms；chunk=1day）
- 压缩：启用 compression（按 `venue_id,instrument_id` 分段；按 `time,id` 排序；30 天后压缩）
- 索引策略：**只保留主键索引**（禁用并删除 Timescale 默认 `*_time_idx`）
- 可读性：提供只读 view 把 `venue_id/instrument_id` 映射回 `exchange/symbol`（避免用 TEXT 做主键）

# 旁路治理表（不污染事实表）
- DDL：`assets/database/db/schema/012_crypto_ingest_governance.sql`
- 表：`crypto.ingest_runs / crypto.ingest_watermark / crypto.ingest_gaps`
- repair 消费者：`python3 -m src repair --dataset crypto.repair.futures.um.trades ...`

---

## 1. “业内成熟”一般意味着什么（说人话版）

> tick-store 的核心目标不是“把数据写进库”，而是：**可信（可审计）、可重跑（可复现）、可扩展（成本可控）、可派生（上层计算稳定）**。

业内成熟的 tick 体系通常具备这些能力（不绑定某个产品）：

- **符号字典化**：事实表用 `instrument_id`（整型）而不是长 `symbol TEXT` 做主键/排序键。
- **文件级审计**：下载/导入严格校验 `.CHECKSUM`，记录 `sha256/size/row_count/min_ts/max_ts`，并能检测“同路径文件被替换”。
- **治理闭环**：实时/回填发现缺口 → 写入 gap 队列 → 自动 repair → 对账关闭缺口（而不是只写日志）。
- **写入与查询的物理优化**：索引最少、排序最贴近查询路径、冷热分层清晰（“当日热数据”与“历史冷数据”策略不同）。
- **可观测**：明确延迟、吞吐、重连、缺口、导入成功率等指标。

---

## 2. 差距对照表（我们现在 vs 成熟做法）

```text
+------------------------+------------------------------+------------------------------+-------------------------------+
| 维度                   | 我们现在                      | 成熟做法                       | 影响/结论                      |
+------------------------+------------------------------+------------------------------+-------------------------------+
| 主键键长               | venue_id/instrument_id=BIGINT | TEXT 主键（反例）              | ✅ 已升级：索引体积/写放大显著下降 |
| 默认索引               | 已禁用 *_time_idx             | 最小索引（按查询加）           | ✅ 已止损                        |
| 文件完整性校验         | sha256/.CHECKSUM 强校验（已落地）| sha256/.CHECKSUM 强校验       | ✅ 已补齐：静默损坏可阻断         |
| 文件版本链审计         | storage.files/import_* + file_revisions（已落地） | 必须落地并自动检测 | ✅ 已补齐：来源可追溯/可复跑      |
| 治理元数据（run/wm/gap)| repair worker 已落地（open->repairing->closed） | 闭环：gap->repair->close | ✅ 已补齐闭环（策略仍可迭代）     |
| 回填策略               | 月+日智能边界 + 404降级        | 同上                           | ✅ 方向正确                      |
| 实时兜底               | stale 触发 REST overlap        | 同上 + 更严格对账              | ✅ MVP 可用；但仍缺严格一致性证明 |
| 数值类型               | NUMERIC(38,12)                | float64 或 scaled-int          | 精确但重；存算成本高             |
| 多交易所/多市场扩展     | exchange/symbol 文本拼表        | 统一 instrument_id 维表锚点     | 现在能用；未来会很痛             |
+------------------------+------------------------------+------------------------------+-------------------------------+
```

---

## 3. “遗漏清单”按优先级排序（越上面越该先做）

### P0（正确性/可审计）

# 3.1 `.CHECKSUM` 已纳入下载/导入闭环（完成）
- 已落地（代码与行为）：
  - 下载同目录的 `.CHECKSUM`，解析目标 ZIP 的 sha256
  - 本地计算 sha256 并对比；不一致则删除并重试（失败写 `storage.import_errors`）
  - 审计落地：`storage.files(checksum_sha256/size_bytes/row_count/min_event_ts/max_event_ts)` + `storage.import_*` + `storage.file_revisions`
- 逃生阀：
  - `--allow-no-checksum`：允许 CHECKSUM 缺失时继续（但必须标记 `verified=false`）

# 3.2 缺口治理闭环已落地（完成）
- 已落地：
  - repair worker：消费 `crypto.ingest_gaps(status='open')`，并发安全认领（`SKIP LOCKED`）
  - 对每个 gap：按 UTC 日期范围触发权威回填（Vision ZIP），成功则 `open->repairing->closed`，失败则 reopen 等待重试
- 入口：
  - `python3 -m src repair --dataset crypto.repair.futures.um.trades ...`

### P1（成本/性能，直接决定你能存多久、写多快）

# 3.3 维度字典化（把 TEXT 从主键挪走）
- 旧问题：`TEXT(exchange/symbol)` 作为主键会导致索引极肥、写入放大明显。
- 成熟补齐（本仓库已按“不保留 v2”的硬约束改为迁移+swap）：
  - 事实表主键：`PRIMARY KEY(venue_id, instrument_id, time, id)`
  - `exchange/symbol` 仅用于展示/入参：通过 `core.venue/core.symbol_map` 映射（view 恢复可读性）
  - 迁移落地：用 `*_new` 临时表导数+对账，最后 rename swap 到同一个正式表名

# 3.4 NUMERIC 的体积与 CPU 成本
- 现状：`NUMERIC(38,12)` 很稳，但贵。
- 取舍建议：
  - 训练/回测特征：优先 `DOUBLE PRECISION`
  - 严格精确对账：使用 scaled-int（例如 price/qty 统一按某个 scale 存 BIGINT），但需要先定“全市场统一 scale 规则”

### P2（可运维/可观测）

# 3.5 缺少“运行指标”
- 现状：主要靠日志。
- 建议最小补齐：
  - 每分钟输出一次：每 symbol 的写入速率、WS 重连次数、当前 lag（now_ms - last_trade_time）
  - 把关键 counters 写入 `ingest_runs.meta`（方便回溯一场 run 的健康度）

---

## 4. 现阶段推荐升级路线（最小增量、最大收益）

> 目标：先把“可信 + 成本”做扎实，再谈派生层与高级查询。

1) **把 `.CHECKSUM` 拉进下载/导入闭环**（P0，已完成）
2) **落地 gap repair worker**（P0，已完成）
3) **上 `venue_id/instrument_id` 的 v2 表**（P1，收益最大）
4) 再考虑数值类型优化（P1，取决于你的精度底线）

---

## 5. 为什么索引会看起来“接近数据一样大”？

# 核心原因（两句话）
- 索引是“第二份按键排序的数据结构”，每行至少多一份：`key + 指针(TID) + B-Tree 结构开销`。
- 当主键里包含 `TEXT`（exchange/symbol）且时间/ID 高基数时，B-Tree 很难压缩，索引天然肥。

# 我们已经做的止损
- 禁用并删除 Timescale 默认 `*_time_idx`，只保留主键索引。

---

## 6. 时区显示（UTC+8）会不会影响物理数据？

# 结论
- 不会影响。物理层存的仍然是 `time(epoch ms)`。
- UTC+8 只是“显示/会话层”的转换：你可以让客户端/JDBC/session 用 `Asia/Shanghai` 显示时间。

---

## 7. 参考（不强依赖，主要用于对照“成熟做法”）

- TimescaleDB（hypertable/indexing/compression）：https://docs.timescale.com/
- kdb+ tick 架构（TP log/RDB/HDB 思路）：https://code.kx.com/
- QuestDB（time-series schema 与分区/列式优化思路）：https://questdb.com/docs/
- ClickHouse（主键/ORDER BY 与存储查询优化思路）：https://clickhouse.com/docs/
