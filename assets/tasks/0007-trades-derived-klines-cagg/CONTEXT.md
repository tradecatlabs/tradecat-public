# CONTEXT

## 已验证能力

- TimescaleDB 在本库已启用（`timescaledb 2.22.1`）。
- 整数时间轴可用 `time_bucket(width, time)`（width 与 time 单位一致）。

## 注意点（必须写死）

- Spot 的 time 单位为 us，而 futures 为 ms：连续聚合脚本必须分开处理（bucket_width 不同）。
- taker buy 的定义基于 `is_buyer_maker`：
  - `is_buyer_maker = false` ⇒ buyer 是 taker ⇒ taker buy（按 Binance 语义）。

