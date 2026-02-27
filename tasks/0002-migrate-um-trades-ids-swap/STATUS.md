# STATUS - 进度真相源

## State

- Status: Done
- Updated: 2026-02-15

## Live Evidence（规划阶段已观察到的事实）

### Evidence 1: 目标库端点可用

- Command: `pg_isready -h localhost -p 15432`
- Observed (excerpt):
  - `localhost:15432 - accepting connections`

### Evidence 2: 运行库现表仍是旧结构（exchange/symbol + NUMERIC）

- Command: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_futures_um_trades"`
- Observed (excerpt):
  - `exchange | text | not null`
  - `symbol   | text | not null`
  - `price/qty/quote_qty | numeric(38,12)`
  - `PRIMARY KEY (exchange, symbol, time, id)`

### Evidence 3: Timescale hypertable 已存在（旧表）

- Command: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT * FROM timescaledb_information.hypertables WHERE hypertable_schema='crypto' AND hypertable_name='raw_futures_um_trades';"`
- Observed (excerpt):
  - `primary_dimension = time`
  - `primary_dimension_type = bigint`

## Execution Evidence（已执行与结果）

### Evidence 4: 旧表规模与窗口（用于迁移评估）

- Command: `SELECT COUNT(*), MIN(time), MAX(time) FROM crypto.raw_futures_um_trades;`
- Observed (excerpt):
  - `rows=6480832`
  - `min_time=1770854400007`
  - `max_time=1770940799906`

### Evidence 5: core 映射已补齐（binance + BTCUSDT）

- Command: `SELECT venue_id, venue_code FROM core.venue;`
- Observed (excerpt):
  - `venue_id=1 venue_code=binance`（后续已迁移为 `binance_futures_um`，见 Evidence 16）
- Command: `SELECT symbol, instrument_id, effective_from FROM core.symbol_map;`
- Observed (excerpt):
  - `BTCUSDT -> instrument_id=1 (effective_from=1970-01-01 UTC)`

### Evidence 6: 新表创建（ids + DOUBLE）并完成全量回迁

- Command: `INSERT INTO crypto.raw_futures_um_trades_new ... SELECT ... FROM crypto.raw_futures_um_trades ...`
- Observed (excerpt):
  - `INSERT 0 6480832`
- Command: `SELECT old_rows, new_rows ...`
- Observed (excerpt):
  - `old_rows=6480832 new_rows=6480832`

### Evidence 7: rename-swap 成功（正式表名不变，旧表保留为 *_old）

- Command: `ALTER TABLE ... RENAME ...`
- Observed (excerpt):
  - `crypto.raw_futures_um_trades` 切换为新列：`venue_id/instrument_id + DOUBLE`
  - `crypto.raw_futures_um_trades_old` 保留旧列：`exchange/symbol + NUMERIC`

### Evidence 8: Timescale 分片轴与 now_func 正常

- Command: `SELECT ... FROM timescaledb_information.dimensions ...`
- Observed (excerpt):
  - `raw_futures_um_trades integer_now_func=unix_now_ms integer_interval=86400000`

### Evidence 9: 压缩策略已存在（30d）

- Command: `SELECT job_id, hypertable_name, config FROM timescaledb_information.jobs ...`
- Observed (excerpt):
  - `raw_futures_um_trades compress_after=2592000000`
  - `raw_futures_um_trades_old compress_after=2592000000`

### Evidence 10: 写库烟囱测试（无“列不存在/类型不匹配”）

- Command: `INSERT ... ON CONFLICT DO NOTHING`（SQL 级 no-op）
- Observed (excerpt):
  - `INSERT 0 0`
- Command: `RawFuturesUmTradesWriter.insert_rows([...])`（代码路径）
- Observed (excerpt):
  - `writer_ok 1`

### Evidence 11: 迁移后体积与索引占比（新/旧对照）

> 说明：hypertable 的真实体积应使用 `hypertable_detailed_size(...)`；`pg_stat_user_tables` 在 hypertable 根表上会显示很小（数据在 chunk 里）。

- Command: `SELECT * FROM hypertable_detailed_size('crypto.raw_futures_um_trades'::regclass);`
- Observed (bytes):
  - `table_bytes=603504640 index_bytes=322273280 total_bytes=925777920 index_pct=34.81%`
- Command: `SELECT * FROM hypertable_detailed_size('crypto.raw_futures_um_trades_old'::regclass);`
- Observed (bytes):
  - `table_bytes=603848704 index_bytes=322273280 total_bytes=926138368 index_pct=34.80%`

### Evidence 12: chunk 边界与压缩状态

- Command: `SELECT * FROM timescaledb_information.chunks ...`
- Observed (excerpt):
  - `raw_futures_um_trades: range=[1770854400000,1770940800000) is_compressed=false`
  - `raw_futures_um_trades_old: range=[1770854400000,1770940800000) is_compressed=false`

### Evidence 13: 压缩策略 job（新/旧均存在）

- Command: `SELECT job_id, hypertable_name, next_start, config FROM timescaledb_information.jobs ...`
- Observed (excerpt):
  - `raw_futures_um_trades job_id=1048 compress_after=2592000000(ms)`
  - `raw_futures_um_trades_old job_id=1046 compress_after=2592000000(ms)`

### Evidence 14: 典型查询走主键索引（范围+排序+limit）

- Command: `EXPLAIN (ANALYZE, BUFFERS) ... WHERE venue_id=1 AND instrument_id=1 AND time BETWEEN ... ORDER BY time,id LIMIT 100`
- Observed (excerpt):
  - `Index Scan using 2_2_raw_futures_um_trades_new_pkey`
  - `Execution Time: ~0.05 ms`（缓存命中场景）

### Evidence 15: 按用户要求删除旧表（释放回滚表）

> 注意：这会移除“rename-swap 直接回滚”的最快路径；需要回滚只能依赖备份或重新迁移。

- Command: `DROP TABLE crypto.raw_futures_um_trades_old;`
- Observed (excerpt):
  - `DROP TABLE`
- Command: `SELECT to_regclass('crypto.raw_futures_um_trades_old');`
- Observed (excerpt):
  - `NULL`
- Command: `SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema='crypto' AND hypertable_name LIKE 'raw_futures_um_trades%';`
- Observed (excerpt):
  - `raw_futures_um_trades`
- Command: `SELECT job_id, hypertable_name FROM timescaledb_information.jobs WHERE hypertable_schema='crypto' AND hypertable_name LIKE 'raw_futures_um_trades%';`
- Observed (excerpt):
  - `job_id=1048 hypertable_name=raw_futures_um_trades`

### Evidence 16: futures_um 的 venue_code 已统一到 product 键空间

> 说明：采集侧已统一使用 `venue_code=binance_futures_um`（避免与 spot/cm 同名 symbol 撞车）；运行库需同步迁移。

- Command: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT venue_id, venue_code FROM core.venue WHERE venue_id=1;"`
- Observed (excerpt):
  - `venue_id=1 venue_code=binance_futures_um`
- Command: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT COUNT(*) FROM core.venue WHERE venue_code='binance';"`
- Observed (excerpt):
  - `count=0`
