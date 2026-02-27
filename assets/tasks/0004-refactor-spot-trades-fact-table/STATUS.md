# STATUS - 进度真相源

## State

- Status: Done
- Updated: 2026-02-15

## Live Evidence（创建任务时已观察到的事实）

### Evidence 1: 运行库 spot 表为 legacy(file_id+time_ts+NUMERIC)

- Command: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_spot_trades"`
- Observed (excerpt):
  - `file_id bigint NOT NULL`（FK 到 storage.files）
  - `time_ts timestamptz NOT NULL`
  - `price/qty/quote_qty numeric(38,12)`
  - `PRIMARY KEY (symbol, time_ts, id)`

### Evidence 2: spot 表当前无数据（0 行）

- Command: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT COUNT(*) FROM crypto.raw_spot_trades;"`
- Observed:
  - `0`

## Execution Evidence（已落地的变更与验证）

### Evidence 3: 迁移脚本已落地并执行（rename-swap）

- Script: `assets/database/db/schema/015_crypto_spot_trades_fact_table.sql`
- Command: `psql "$DATABASE_URL" -f assets/database/db/schema/015_crypto_spot_trades_fact_table.sql`
- Observed:
  - 新表 `crypto.raw_spot_trades` 列为 `venue_id/instrument_id + DOUBLE + time(us)`
  - 旧表保留为 `crypto.raw_spot_trades_old`

### Evidence 4: 表结构/Timescale/压缩策略通过（AC1-AC2）

- Command: `psql "$DATABASE_URL" -c "\\d+ crypto.raw_spot_trades"`
- Observed (excerpt):
  - `PRIMARY KEY (venue_id, instrument_id, time, id)`
- Command: `psql "$DATABASE_URL" -c "SELECT integer_interval, integer_now_func FROM timescaledb_information.dimensions WHERE hypertable_schema='crypto' AND hypertable_name='raw_spot_trades';"`
- Observed (excerpt):
  - `integer_interval=86400000000`
  - `integer_now_func=unix_now_us`
- Command: `psql "$DATABASE_URL" -c "SELECT job_id, config FROM timescaledb_information.jobs WHERE hypertable_schema='crypto' AND hypertable_name='raw_spot_trades';"`
- Observed (excerpt):
  - `compress_after=2592000000000`

### Evidence 5: writer 冒烟通过（插入 1 行→按 PK 删除）

- Observed:
  - `writer_insert_rows 1`
  - `writer_smoke_cleanup_ok`

### Evidence 6: Vision 回填 1 天通过（BTCUSDT@2026-02-12）

- Command: `python3 -m src backfill --dataset crypto.data_download.spot.trades --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
- Observed:
  - `affected=6778280 file_rows=6778280`
- Command: `psql "$DATABASE_URL" -c "SELECT rel_path, checksum_sha256, row_count FROM storage.files ORDER BY file_id DESC LIMIT 2;"`
- Observed:
  - spot ZIP 的 `rel_path + checksum_sha256 + row_count` 已落 `storage.files`
