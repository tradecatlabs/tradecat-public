# CONTEXT

## 当前状态

- 这三类采集器均为占位 `raise NotImplementedError`：
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/um/bookTicker.py`
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/um/bookDepth.py`
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/um/metrics.py`
  - 对应 download 版本同样占位（`.../data_download/...`）

## 风险与难点

- `metrics` 字段是否能通过 ccxt 直接拉取并“逐字段对齐”不确定；因此本任务优先 ZIP 回填作为唯一真相源。
- `bookDepth` 属于“百分比深度曲线”，若未来要实时生成，需要明确算法合同；本任务先以官方 ZIP 为准。

