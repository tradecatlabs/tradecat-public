# 0009 - futures-cm-book-metrics-ingestion

## 价值（Why）

futures/cm 与 futures/um 在目录/字段上高度对称。UM 版本成熟后，CM 应复用同一套下载回填、审计、治理逻辑，保证两条产品线的数据工程一致性。

## 范围（Scope）

### In Scope

- 实现下载回填卡片：
  - `crypto.data_download.futures.cm.bookTicker`
  - `crypto.data_download.futures.cm.bookDepth`
  - `crypto.data_download.futures.cm.metrics`
- 入库目标：
  - `crypto.raw_futures_cm_book_ticker`
  - `crypto.raw_futures_cm_book_depth`
  - `crypto.raw_futures_cm_metrics`

### Out of Scope

- 不重复造轮子：优先抽象 UM 的通用实现，CM 仅做路径/参数差异。

