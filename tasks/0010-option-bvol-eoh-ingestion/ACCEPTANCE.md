# ACCEPTANCE

## AC1｜两类 dataset 的 backfill 可运行

- 命令（示例）：
  - `python3 -m src backfill --dataset crypto.data_download.option.BVOLIndex --symbols BTCBVOLUSDT --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
  - `python3 -m src backfill --dataset crypto.data_download.option.EOHSummary --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
- 通过条件：均能运行完成，表中有行数增长，且 `storage.files` 有审计记录。

## AC2｜空值处理符合样本

- 验证：针对 EOHSummary 中可能为空的字段（如 best_buy_iv/mark_price 等），导入后为 NULL 而不是异常/0。
- 通过条件：抽样对账通过。

