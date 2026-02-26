# ACCEPTANCE

## AC1｜三类 dataset 的 backfill 可运行

- 命令（示例）：
  - `python3 -m src backfill --dataset crypto.data_download.futures.um.bookTicker --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
  - `python3 -m src backfill --dataset crypto.data_download.futures.um.bookDepth --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
  - `python3 -m src backfill --dataset crypto.data_download.futures.um.metrics --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
- 通过条件：均能运行完成，且 `crypto.ingest_runs` 有记录。

## AC2｜字段对齐官方 CSV

- 验证：抽样 1 个 CSV，逐列比对（列数/顺序/类型可解析）。
- 通过条件：入库字段与官方字段一一对应，不丢列、不乱改语义。

## AC3｜storage.files 审计闭环

- 验证：`storage.files` 中存在对应 `rel_path/checksum_sha256/row_count/min_event_ts/max_event_ts`。
- 通过条件：可追溯到具体 ZIP/CSV 文件。

