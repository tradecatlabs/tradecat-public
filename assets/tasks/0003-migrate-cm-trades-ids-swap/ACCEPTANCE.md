# ACCEPTANCE - 精密验收标准

> 任务编号：0003
> 原则：每条 AC 都必须可执行 + 可判定。

## A. 表结构与 Timescale（必须先过）

### AC1：CM trades 表升级为 ids+DOUBLE

- 命令：`PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_futures_cm_trades"`
- 通过条件：
  - 列为：`venue_id, instrument_id, id, price(double precision), qty(double precision), quote_qty(double precision), time(bigint), is_buyer_maker(boolean)`
  - `PRIMARY KEY (venue_id, instrument_id, time, id)`

### AC2：integer hypertable + now_func 正常

- 命令：
  - `psql "$DATABASE_URL" -c "SELECT * FROM timescaledb_information.dimensions WHERE hypertable_schema='crypto' AND hypertable_name='raw_futures_cm_trades';"`
- 通过条件：
  - `dimension_type='time'`
  - `integer_interval=86400000`（ms = 1 day）
  - `integer_now_func` 为 `crypto.unix_now_ms`（或等价函数名，但必须返回 ms）

### AC3：压缩启用 + policy job 存在（30d）

- 命令：
  - `psql "$DATABASE_URL" -c "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_schema='crypto' AND hypertable_name='raw_futures_cm_trades';"`
  - `psql "$DATABASE_URL" -c "SELECT job_id, hypertable_name, config FROM timescaledb_information.jobs WHERE hypertable_schema='crypto' AND hypertable_name='raw_futures_cm_trades';"`
- 通过条件：
  - `compression_enabled = t`
  - `config` 里 `compress_after=2592000000`（ms，30d）

## B. 写库烟囱（最小可用）

### AC4：最小 writer 冒烟（幂等 + 可清理）

- 操作：
  - 通过新 writer 插入 1 条测试行（`INSERT ... ON CONFLICT DO NOTHING`），并按 PK 删除（不留脏数据）。
- 通过条件：
  - 不出现“列不存在/类型不匹配”
  - 删除后 COUNT 不增加

## C. 回填路径（可选但推荐）

### AC5：Vision 回填 1 天（任意有效 symbol）

- 操作：运行 CM 的 backfill 卡片导入 1 天（symbol TBD，以 Vision 实际存在为准）。
- 通过条件：
  - `crypto.raw_futures_cm_trades` 在该 UTC 日窗口内行数 > 0
  - `storage.files` 出现该 ZIP 的 `checksum_sha256/row_count/min_event_ts/max_event_ts`

