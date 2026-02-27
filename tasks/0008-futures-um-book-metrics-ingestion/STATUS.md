# STATUS

Status: Done

## Evidence Log

- 已实现 3 个回填卡片（download_and_ingest）：
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/bookTicker.py`
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/bookDepth.py`
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/metrics.py`
- 已抽出通用工具（避免重复造轮子）：
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data_download/_plan_utils.py`（monthly/daily 智能边界）
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data_download/_zip_utils.py`（CHECKSUM + ZIP 校验）
- CLI backfill choices 已补齐并可运行：`services/ingestion/binance-vision-service/src/__main__.py`
- 运行库冒烟（`localhost:15432/market_data`）：
  - metrics：`python3 -m src backfill --dataset crypto.data_download.futures.um.metrics --symbols BTCUSDT --start-date 2026-02-14 --end-date 2026-02-14 --no-files`
    - `crypto.raw_futures_um_metrics` 当天行数：287
    - `storage.files` 存在 `data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-02-14.zip`（row_count=287, meta.verified=true）
    - `crypto.ingest_runs(dataset='futures.um.metrics')` 最新 run status=success（meta 内含 plan/download/ingest 统计）
  - bookDepth：`python3 -m src backfill --dataset crypto.data_download.futures.um.bookDepth --symbols BTCUSDT --start-date 2026-02-14 --end-date 2026-02-14 --no-files`
    - `crypto.raw_futures_um_book_depth` 当天行数：32748
    - `storage.files` 存在 `data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2026-02-14.zip`（row_count=32748, meta.verified=true）
    - `crypto.ingest_runs(dataset='futures.um.bookDepth')` 最新 run status=success
  - bookTicker：已用最小合成 ZIP 做本地入库冒烟（不污染事实表，执行后已清理测试行/测试 file 记录），验证 COPY→INSERT→幂等键路径可用。
