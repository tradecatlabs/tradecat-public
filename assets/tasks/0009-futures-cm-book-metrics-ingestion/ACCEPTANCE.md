# ACCEPTANCE

## AC1｜三类 dataset 的 backfill 可运行（CM）

- 命令（示例）：
  - `python3 -m src backfill --dataset crypto.data_download.futures.cm.bookTicker --symbols BTCUSD_PERP --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
  - `python3 -m src backfill --dataset crypto.data_download.futures.cm.bookDepth --symbols BTCUSD_PERP --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
  - `python3 -m src backfill --dataset crypto.data_download.futures.cm.metrics --symbols BTCUSD_PERP --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
- 通过条件：均能运行完成并落审计。

