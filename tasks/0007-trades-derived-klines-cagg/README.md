# 0007 - trades-derived-klines-cagg

## 价值（Why）

逐笔能合成 K 线，但如果每次训练/回测都现场扫全量 trades，会非常慢且昂贵。  
本任务在不新建“派生物理表”的前提下，优先使用 TimescaleDB 的 **continuous aggregates（连续聚合）** 把 trades 变成可用的 1m/5m/... K 线序列：既可追溯（源头仍是 trades），又能稳定支撑训练/回测。

## 范围（Scope）

### In Scope

- 基于以下事实表构建派生序列：
  - `crypto.raw_futures_um_trades`（ms）
  - `crypto.raw_futures_cm_trades`（ms）
  - `crypto.raw_spot_trades`（us）
- 产出最小集合：
  - `1m` K 线（OHLCV + count + taker_buy_volume/taker_buy_quote_volume）
  - 后续周期（5m/15m/1h/4h/1d）可复用同一生成器函数按需扩展
- 保持“单一真相源”：K 线只来自 trades（不允许多头写入）。

### Out of Scope

- 不接入 Binance Vision 官方 klines CSV 入库（那是外部派生数据，可选；本任务目标是自派生）。
- 不做指标计算（trading-service 负责）。

