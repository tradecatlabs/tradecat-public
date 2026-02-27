# Binance Vision UM trades：离线本地导入（local-only）

目标：在**不联网**的情况下，把已存在于本机 `data_download/` 的 Binance Vision ZIP，直接导入到 `crypto.raw_futures_um_trades`，并保持可审计、可重跑、可压缩落地。

## 1) 前置条件（必须满足）

- 运行库为 TimescaleDB，且 `crypto.raw_futures_um_trades` 已是 ids 结构（`venue_id/instrument_id` + `DOUBLE` + integer hypertable）。
- `storage.files` 与 `crypto.ingest_runs` 已存在（用于审计证据链）。
- 表已启用压缩策略（`compress_after`），否则全历史导入会快速爆盘。

## 2) 本地文件布局（必须与官方一致）

服务根目录：

- `services/ingestion/binance-vision-service/data_download/futures/um/monthly/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM.zip`
- `services/ingestion/binance-vision-service/data_download/futures/um/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.zip`

注意：`storage.files.rel_path` 记录的是官方目录（以 `data/futures/...` 开头），与本地落盘目录（以 `data_download/...` 开头）不同；这是刻意设计，用于“官方路径可对照、落盘路径可隔离”。

## 3) 执行命令（BTC 全量示例）

```bash
cd services/ingestion/binance-vision-service
export BINANCE_VISION_DATABASE_URL='postgresql://postgres:postgres@localhost:15432/market_data'

# 建议：先 BTC 再扩展其他 symbol
PYTHONUNBUFFERED=1 python3 -m src backfill \
  --dataset crypto.data_download.futures.um.trades \
  --symbols BTCUSDT \
  --start-date 2019-09-01 \
  --end-date 2026-02-12 \
  --local-only \
  --workers 3
```

说明：

- `--local-only`：只 ingest 本地 ZIP，不下载、不请求 CHECKSUM。
- `--workers N`：并发导入 worker 数（仅 UM trades 支持）。
- 默认更稳（`synchronous_commit=on`）；如你明确要极致速度，可额外设置 `TC_UNSAFE_FAST_INGEST=1`（崩溃时可能丢最后一小段已提交事务）。

## 4) 运行中复核（建议每小时看一次）

- 文件审计：`storage.files` 中对应 `rel_path` 的 `row_count/min_event_ts/max_event_ts` 是否持续增长。
- 压缩覆盖：窗口导入后，`timescaledb_information.chunks` 中命中的 chunk 应逐步变为 `is_compressed=true`（避免 uncompressed 越积越多）。
- 旁路 meta：`crypto.ingest_runs.meta` 中的 `file_rows_total/affected_rows_total/chunks_compressed_total/skip_existing` 是否合理。

## 5) 可重跑语义（重要）

- 事实表：以主键幂等去重；同一文件/窗口重复导入不会产生重复行（但会有写入成本）。
- 审计层：以 `storage.files(rel_path)` 做文件级“已入库”判断，已完成文件会跳过；跳过路径仍会补做必要压缩（防爆盘）。
