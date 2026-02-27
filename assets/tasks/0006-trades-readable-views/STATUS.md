# STATUS

Status: Done

## Evidence Log

- 已生成并纳入 DDL：`assets/database/db/schema/016_crypto_trades_readable_views.sql`
- 运行库验证（`localhost:15432/market_data`）：
  - `to_regclass('crypto.vw_futures_um_trades')` / `...cm...` / `...spot...` 均为非 NULL
  - `SELECT * FROM crypto.vw_futures_um_trades LIMIT 1;` 可正常返回
  - `time_ts_cn = time_ts_utc AT TIME ZONE 'Asia/Shanghai'`（UTC+8 仅展示，不影响物理表）
- join 语义：`symbol_map` 采用 `LATERAL + ORDER BY effective_from DESC + LIMIT 1`，避免行数放大（见 DDL）。
