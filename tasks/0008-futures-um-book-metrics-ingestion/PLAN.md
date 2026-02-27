# PLAN

## 策略

- 以 Vision ZIP 回填为“源头真相”，保证字段与目录结构 100% 对齐。
- writer 复用 trades backfill 的通用组件：
  - 下载（checksum 校验）
  - 解压（csv）
  - `storage.files` 记录（zip/csv 关联）
  - 分批 COPY/INSERT 入库
  - `ingest_runs/meta` 写入条数/耗时/校验信息

## 交付物

- 新增对应 writer（如需要）：
  - `src/writers/raw_futures_um_book_ticker.py`（或复用通用 writer）
  - `src/writers/raw_futures_um_book_depth.py`
  - `src/writers/raw_futures_um_metrics.py`
- 实现 download collectors：
  - `src/collectors/crypto/data_download/futures/um/{bookTicker,bookDepth,metrics}.py`
- CLI choices 增加对应 dataset。

