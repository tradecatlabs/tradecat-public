# STATUS

Status: Done

## Evidence Log

- 已生成并纳入 DDL：`libs/database/db/schema/017_crypto_trades_cagg_klines.sql`
- 运行库验证（`localhost:15432/market_data`）：
  - `timescaledb_information.continuous_aggregates` 存在 3 个 cagg：
    - `crypto.cagg_futures_um_klines_1m`
    - `crypto.cagg_futures_cm_klines_1m`
    - `crypto.cagg_spot_klines_1m`
  - `timescaledb_information.jobs` 存在 refresh policy（`proc_name=policy_refresh_continuous_aggregate`）：`job_id=1051/1052/1053`
  - materialization hypertable：`_materialized_hypertable_122/_123/_124`（对应 UM/CM/Spot）
