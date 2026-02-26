# CONTEXT - 现状与风险图谱

> 任务编号：0002

## 现状追溯（必须先锁定的事实）

### 1) 仓库 DDL 的“目标表结构”已经切到 ids + DOUBLE

- 真相源：`libs/database/db/schema/009_crypto_binance_vision_landing.sql:71-115`
  - `crypto.raw_futures_um_trades(venue_id BIGINT, instrument_id BIGINT, price/qty/quote_qty DOUBLE PRECISION, PRIMARY KEY(venue_id,instrument_id,time,id))`

### 2) 采集写库代码已经按 ids 列写入（不再写 exchange/symbol）

- 实时写入器：`services/ingestion/binance-vision-service/src/writers/raw_futures_um_trades.py:45-66`
  - `INSERT INTO crypto.raw_futures_um_trades (venue_id, instrument_id, ...)`
  - `ON CONFLICT (venue_id, instrument_id, time, id) DO NOTHING`
- 回填写入器：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/trades.py:343-364`
  - `INSERT INTO crypto.raw_futures_um_trades (venue_id, instrument_id, ...)`
  - `ON CONFLICT ... DO UPDATE`（官方回填为准）

### 3) 运行库（localhost:15432/market_data）的现表仍是旧结构（会直接打崩新写库）

- 证据：`psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_futures_um_trades"`
- 观察到（摘要）：
  - 列：`exchange text, symbol text, price/qty/quote_qty numeric(38,12), time bigint`
  - PK：`(exchange, symbol, time, id)`

结论：**必须先做 DB 迁移（rename-swap），否则新采集链路连接该库会报 “column venue_id/instrument_id does not exist”。**

---

## 约束矩阵（必须遵守）

- 不修改 `config/.env`（只读）。
- 不污染事实表：事实表仍坚持“极简 raw”，不加 `file_id/ingested_at/time_ts`。
- 不丢数据：迁移期必须保留旧表（`*_old`）以便回滚与对账。
- 不引入新业务依赖：迁移只用 `psql`/SQL（允许用现有 `core.*` 维表）。

---

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :---: | :--- | :--- |
| 迁移时仍有写入导致数据不一致 | High | copy 期间 `crypto.raw_futures_um_trades` 行数持续变化 | 迁移窗口先停写（停采集/停回填），或至少切只读；copy 分批 + 最后增量补拷贝 |
| WAL/磁盘暴涨导致 PG 抖动 | High | `pg_stat_wal` 增长异常、磁盘告警 | 分批迁移（按日/按 chunk），控制单事务规模；必要时迁移期 `SET synchronous_commit=off`（可重跑） |
| Timescale 压缩策略在回迁期间抢资源 | Medium | 后台压缩 job 与 copy 抢 IO/CPU | 迁移期先不添加压缩 policy；全部验收后再 `add_compression_policy` |
| 映射错误（symbol → instrument_id）导致数据归属错 | High | 同一 symbol 出现多个 instrument_id；或出现 unmapped rows | 迁移前先构建 core 映射；迁移后做一致性查询（每 symbol 必须 1 个 instrument_id） |
| rename-swap 锁表造成长时间阻塞 | Medium | `ALTER TABLE ... RENAME` 卡住、业务连接堆积 | 只在最后一步 swap；提前预热/验证；设置 `lock_timeout`，超时即回滚 |
| 回填 DO UPDATE 触碰已压缩 chunk 导致性能灾难 | Medium | 回填旧日期时出现 decompress/recompress | 写死硬规则：压缩窗口之后禁止 UPDATE（或走显式 decompress 例外流程） |

---

## 假设与证伪（执行前必须逐条确认）

1) 目标数据库端点是 `localhost:15432/market_data`（postgres/postgres）  
   - Verify: `pg_isready -h localhost -p 15432 && PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT 1;"`

2) `crypto.raw_futures_um_trades` 目前仍为旧列（exchange/symbol）  
   - Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_futures_um_trades"`

3) TimescaleDB 扩展可用（hypertable/压缩函数存在）  
   - Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT extname FROM pg_extension WHERE extname IN ('timescaledb');"`

4) 旧表中的 exchange 值是 base 交易所代码（例如 `binance`）；写入 ids 时必须把 product 折叠进 `core.venue.venue_code`（UM= `binance_futures_um`）  
   - Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT exchange, COUNT(*) FROM crypto.raw_futures_um_trades GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"`

5) 迁移窗口允许暂停采集写入（避免 copy 时数据漂移）  
   - Verify: 运维确认 + `pg_stat_activity` 无写入会话
