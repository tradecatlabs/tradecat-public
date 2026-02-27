# 0008 - futures-um-book-metrics-ingestion

## 价值（Why）

在“逐笔 trades”之外，futures/um 的 `bookTicker/bookDepth/metrics` 属于你定义的原子数据：  
它们直接来自交易所/官方统计，无法从 trades 完整还原，是训练/风控/微观结构分析的重要补充。

本任务把这三类数据集从“占位”补齐到可长期运行：回填（Vision ZIP）→ 审计（storage.files）→ 入库（crypto.raw_*）→ 治理（ingest_runs/watermark/gaps）。

## 范围（Scope）

### In Scope

- 实现下载回填卡片：
  - `crypto.data_download.futures.um.bookTicker`
  - `crypto.data_download.futures.um.bookDepth`
  - `crypto.data_download.futures.um.metrics`
- 目录/文件命名严格对齐 Binance Vision：
  - `data/futures/um/{daily|monthly}/{dataset}/{SYMBOL}/...`
- 入库目标：
  - `crypto.raw_futures_um_book_ticker`
  - `crypto.raw_futures_um_book_depth`
  - `crypto.raw_futures_um_metrics`

### Out of Scope

- 实时 WS 采集是否补齐：本任务以“官方 ZIP 回填”优先，WS 仅在字段可稳定对齐时再做（避免造出与官方不一致的数据）。

