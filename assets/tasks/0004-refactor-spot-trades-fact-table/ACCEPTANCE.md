# ACCEPTANCE - 精密验收标准

> 任务编号：0004

## A. 表结构（必须先过）

### AC1：raw_spot_trades 重构为极简事实表（ids+DOUBLE+epoch_us）

- 命令：`PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_spot_trades"`
- 通过条件：
  - 不再出现：`file_id, symbol, time_ts, ingested_at`
  - 列应包含（允许顺序不同）：
    - `venue_id BIGINT NOT NULL`
    - `instrument_id BIGINT NOT NULL`
    - `id BIGINT NOT NULL`
    - `price/qty/quote_qty DOUBLE PRECISION NOT NULL`
    - `time BIGINT NOT NULL`（epoch(us)）
    - `is_buyer_maker BOOLEAN NOT NULL`
    - `is_best_match BOOLEAN`（允许 NULL）
  - PK：`PRIMARY KEY (venue_id, instrument_id, time, id)`

### AC2：Timescale integer hypertable（us 时间轴）+ 压缩策略

- 命令：
  - `psql "$DATABASE_URL" -c "SELECT * FROM timescaledb_information.dimensions WHERE hypertable_schema='crypto' AND hypertable_name='raw_spot_trades';"`
  - `psql "$DATABASE_URL" -c "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_schema='crypto' AND hypertable_name='raw_spot_trades';"`
- 通过条件：
  - `integer_interval = 86400000000`（us = 1 day）
  - `compression_enabled = t`

## B. 写库链路（最小可用）

### AC3：writer 冒烟（插入 1 行→删除）

- 通过条件：
  - 可 insert 且 conflict 语义正确（重复插入不产生新行）
  - 删除后不留脏数据

### AC4：Vision 回填 1 天（BTCUSDT 或任意有效 symbol）

- 操作：`python3 -m src backfill --dataset crypto.data_download.spot.trades --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12`
- 通过条件：
  - `crypto.raw_spot_trades` 该日窗口行数 > 0
  - `storage.files` 对应 `rel_path` 有 `checksum_sha256/row_count/min_event_ts/max_event_ts`

