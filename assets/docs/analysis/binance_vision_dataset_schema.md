# Binance Data Vision：目录层级与 CSV 字段契约（对齐草案）

> 目的：把 `data.binance.vision` 的“目录分类 + CSV 字段”固化为工程契约，用于后续设计 `raw_*` 表与解析器。  
> 说明：本契约来自本仓库的 BTC 样本罗盘分析（见 `assets/artifacts/analysis/binance_vision_compass/*`），覆盖：`futures/`、`spot/`、`option/` 的 daily 数据集子集。

---

## 1) 顶层目录（Top Level）

- `futures/`：期货（本次样本为 `um` USDT-M）
- `spot/`：现货
- `option/`：期权

落盘建议：保持与官网一致的层级（用于可复现与增量同步），例如：

```
data/
├── futures/um/daily/...
├── spot/daily/...
└── option/daily/...
```

---

## 2) Futures / UM / daily（样本覆盖）

### 2.1 aggTrades

- 文件：`futures/um/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-YYYY-MM-DD.zip`
- CSV（**有 header**，时间戳 **ms**）：
  - `agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker`

### 2.2 trades

- 文件：`futures/um/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.zip`
- CSV（**有 header**，时间戳 **ms**）：
  - `id, price, qty, quote_qty, time, is_buyer_maker`

### 2.3 klines / markPriceKlines / indexPriceKlines / premiumIndexKlines（1m）

- 文件（示例）：`futures/um/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.zip`
- CSV（**有 header**，时间戳 **ms**）：
  - `open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore`

> 映射到 `market_data.candles_1m`：`bucket_ts = open_time`（UTC 对齐到 minute），`quote_volume/count/taker_buy_*` 直接对齐字段。

### 2.4 bookTicker

- 文件：`futures/um/daily/bookTicker/{SYMBOL}/{SYMBOL}-bookTicker-YYYY-MM-DD.zip`
- CSV（**有 header**，时间戳 **ms**）：
  - `update_id, best_bid_price, best_bid_qty, best_ask_price, best_ask_qty, transaction_time, event_time`

### 2.5 bookDepth

- 文件：`futures/um/daily/bookDepth/{SYMBOL}/{SYMBOL}-bookDepth-YYYY-MM-DD.zip`
- CSV（**有 header**）：
  - `timestamp, percentage, depth, notional`

> 该数据是“按档位百分比聚合”的深度曲线（不是逐笔 order book 增量），适合做流动性剖面/冲击成本估计。

### 2.6 metrics

- 文件：`futures/um/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-YYYY-MM-DD.zip`
- CSV（**有 header**）：
  - `create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio`

> 映射到 `market_data.binance_futures_metrics_5m`：`create_time` 需对齐到 5 分钟边界（本仓库 backfill 已按 5m 向下取整）。

---

## 3) Spot / daily（样本覆盖）

### 3.1 aggTrades

- 文件：`spot/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-YYYY-MM-DD.zip`
- CSV（**无 header**，时间戳 **微秒 us（16 位）**）：
  - `agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time_us, is_buyer_maker, is_best_match`

### 3.2 trades

- 文件：`spot/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.zip`
- CSV（**无 header**，时间戳 **微秒 us（16 位）**）：
  - `id, price, qty, quote_qty, time_us, is_buyer_maker, is_best_match`

### 3.3 klines（1m）

- 文件：`spot/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.zip`
- CSV（**无 header**，时间戳 **微秒 us（16 位）**）：
  - `open_time_us, open, high, low, close, volume, close_time_us, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore`

> 风险点：现有 `data-service` 的 ZIP 回填逻辑假设时间戳为 ms（仅覆盖 futures/um/klines）。如要支持 spot，需要在解析器里按“位数/路径”区分 ms vs us 并统一归一化。

---

## 4) Option / daily（样本覆盖）

### 4.1 BVOLIndex

- 文件：`option/daily/BVOLIndex/{SYMBOL}/{SYMBOL}-BVOLIndex-YYYY-MM-DD.zip`（样本为 `BTCBVOLUSDT`）
- CSV（**有 header**，时间戳 **ms**）：
  - `calc_time, symbol, base_asset, quote_asset, index_value`

### 4.2 EOHSummary

- 文件：`option/daily/EOHSummary/{UNDERLYING}/{UNDERLYING}-EOHSummary-YYYY-MM-DD.zip`（样本为 `BTCUSDT`）
- CSV（**有 header**）字段较多，样本头部为：
  - `date, hour, symbol, underlying, type, strike, open, high, low, close, volume_contracts, volume_usdt, ... , openinterest_contracts, openinterest_usdt`

---

## 5) 归一化建议（Parser Contract）

1) **Header 兼容**
   - 有 header：按列名解析；
   - 无 header：按“数据集类型 + 固定列序”解析（不得猜测）。

2) **时间戳单位**
   - `13 位` → 毫秒 `ms`
   - `16 位` → 微秒 `us`（需要除以 1000 归一为 ms，或直接转 `datetime`）

3) **建议的最小落库策略（MVP）**
   - 先只落：`futures/um/klines` 与 `metrics`（本仓库已覆盖并有表）
   - 其他数据集（trades/aggTrades/bookTicker/bookDepth/option）先落 `raw_*`（JSONB 或“窄表 + payload_json”），再按需要做派生
