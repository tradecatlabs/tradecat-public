# Futures UM bookDepth/bookTicker：全量采集整理入库规划（BTCUSDT 起步）

> 目标：把 `bookDepth` 与 `bookTicker` 从“有表/有卡片/能冒烟”推进到**可长期全量补齐**：可追溯、可重跑、可对账、成本可控。
>
> 前提：你已经把 `futures/um/trades` 做成 ids 事实表（本仓库已落地）。

---

## 0) 现状（代码/DDL 已具备的能力）

### 0.1 数据集卡片（已实现）

- `crypto.data_download.futures.um.bookDepth`
  - 实现：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/bookDepth.py`
  - 支持：daily + monthly（404 自动降级按日），`.CHECKSUM` 校验（可用 `--allow-no-checksum` 逃生）
- `crypto.data_download.futures.um.bookTicker`
  - 实现：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/bookTicker.py`
  - 支持：daily + monthly（404 自动降级按日），`.CHECKSUM` 校验（可用 `--allow-no-checksum` 逃生）

### 0.2 落库表（已存在）

- DDL：`assets/database/db/schema/009_crypto_binance_vision_landing.sql`
- 表：
  - `crypto.raw_futures_um_book_depth`（ids + DOUBLE；integer hypertable: `timestamp` BIGINT(ms)，chunk=7d，compress_after=30d）
  - `crypto.raw_futures_um_book_ticker`（ids + DOUBLE；integer hypertable: `event_time` BIGINT(ms)，chunk=1d，compress_after=3d）

运行库迁移（若你本机仍是旧结构 file_id/symbol + NUMERIC + timestamptz）：
- 脚本：`assets/database/db/schema/020_crypto_futures_book_ids_swap.sql`
- 方式：rename-swap，保留 `*_old`（不删除数据）

### 0.3 可追溯/治理旁路（已存在）

- 文件证据链：`storage.files / storage.file_revisions / storage.import_batches / storage.import_errors`
- 运行元数据：`crypto.ingest_runs(meta jsonb)`（回填结束写入统计）
- watermark：回填会按最大时间更新 watermark（便于后续治理/缺口修复）

---

## 1) 数据契约（必须严格对齐官方）

### 1.1 bookDepth（Vision ZIP）

- 官方路径：
  - `data/futures/um/daily/bookDepth/{SYMBOL}/{SYMBOL}-bookDepth-YYYY-MM-DD.zip`
  - `data/futures/um/monthly/bookDepth/{SYMBOL}/{SYMBOL}-bookDepth-YYYY-MM.zip`
- CSV header：`timestamp,percentage,depth,notional`
- 时间语义：`timestamp` 约定按 UTC 解析（代码已 `SET TIME ZONE 'UTC'`）

### 1.2 bookTicker（Vision ZIP）

- 官方路径：
  - `data/futures/um/daily/bookTicker/{SYMBOL}/{SYMBOL}-bookTicker-YYYY-MM-DD.zip`
  - `data/futures/um/monthly/bookTicker/{SYMBOL}/{SYMBOL}-bookTicker-YYYY-MM.zip`
- CSV header：`update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time`
- 时间语义：
  - `event_time` 为 epoch(ms)
  - `transaction_time` 允许为空

---

## 2) “全量采集”的正确做法：先定范围，再跑全量（避免 404 垃圾与审计污染）

> 现实：某些数据集并不从 2019 开始；如果你从 2019 起跑，会产生海量 daily 404，导致 `storage.import_errors` 与 `storage.files(meta.error)` 被污染，后续审计会变脏。

### 2.1 推荐策略（强烈建议）

1) **先跑近 7 天**（验证下载→校验→入库→压缩→对账闭环完全正确）  
2) **再扩到近 90 天**（把性能/体积/压缩策略跑出来）  
3) **最后做“向过去扩展”**：以月为单位往前推进，直到出现连续一段“全 404”，再把那段之前视为“该数据集不可用起点”并停止继续向前。

这套策略的核心是：你永远只把“真实存在的数据”写进审计系统，避免把“官方不存在”误当成“采集失败”。

---

## 3) 执行流程（可直接照着跑）

### 3.1 预检（只跑一次）

```bash
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data \
  -c "\\d crypto.raw_futures_um_book_depth" \
  -c "\\d crypto.raw_futures_um_book_ticker" \
  -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';"
```

### 3.2 bookDepth：近 7 天冒烟 → 90 天 → 全量推进

```bash
cd services/ingestion/binance-vision-service
BINANCE_VISION_DATABASE_URL='postgresql://postgres:postgres@localhost:15432/market_data' \
BINANCE_DATA_BASE='https://data.binance.vision' \
python3 -m src backfill \
  --dataset crypto.data_download.futures.um.bookDepth \
  --symbols BTCUSDT \
  --start-date 2026-02-09 \
  --end-date   2026-02-15 \
  --no-files
```

### 3.3 bookTicker：同样分段推进（先小窗验证，再扩大）

> bookTicker 通常比 bookDepth 大得多；务必先用小窗验证性能与磁盘/压缩曲线。

```bash
cd services/ingestion/binance-vision-service
BINANCE_VISION_DATABASE_URL='postgresql://postgres:postgres@localhost:15432/market_data' \
BINANCE_DATA_BASE='https://data.binance.vision' \
python3 -m src backfill \
  --dataset crypto.data_download.futures.um.bookTicker \
  --symbols BTCUSDT \
  --start-date 2024-01-01 \
  --end-date   2024-01-01 \
  --no-files
```

### 3.4 验收（每次扩窗后都跑）

```bash
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data \
  -c "SELECT market,product,dataset,COUNT(*) AS n_files,SUM(row_count) AS rows FROM storage.files GROUP BY 1,2,3 ORDER BY 1,2,3;" \
  -c "SELECT exchange,dataset,status,COUNT(*) AS n FROM crypto.ingest_runs GROUP BY 1,2,3 ORDER BY 1,2,3;"
```

对账（抽样日窗，不要全表扫描）：

```sql
-- 例：对账某一天（UTC 日窗）
WITH ids AS (
  SELECT v.venue_id, sm.instrument_id
  FROM core.venue v
  JOIN core.symbol_map sm
    ON sm.venue_id = v.venue_id
   AND sm.symbol = 'BTCUSDT'
   AND sm.effective_to IS NULL
  WHERE v.venue_code = 'binance_futures_um'
)
SELECT
  'bookDepth' AS dataset,
  (SELECT row_count FROM storage.files WHERE rel_path = 'data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2026-02-14.zip') AS file_rows,
  (SELECT COUNT(*)
   FROM crypto.raw_futures_um_book_depth d, ids
   WHERE d.venue_id = ids.venue_id
     AND d.instrument_id = ids.instrument_id
     AND d.timestamp >= (EXTRACT(EPOCH FROM '2026-02-14 00:00:00+00'::timestamptz) * 1000)::bigint
     AND d.timestamp <  (EXTRACT(EPOCH FROM '2026-02-15 00:00:00+00'::timestamptz) * 1000)::bigint
  ) AS fact_rows;
```

### 3.5 实时采集（WS，作为“当天数据”补齐与延迟覆盖）

> 说明：
> - `bookTicker` 是 WS-only 语义（REST 快照不等价），实时必须走 `ccxt.pro` WebSocket。
> - 当天的数据通常靠实时先落库；后续官方 ZIP 到了再用 backfill 做权威对账与补齐。

```bash
cd services/ingestion/binance-vision-service
BINANCE_VISION_DATABASE_URL='postgresql://postgres:postgres@localhost:15432/market_data' \
python3 -m src collect \
  --dataset crypto.data.futures.um.bookTicker \
  --symbols BTCUSDT \
  --no-csv
```

```bash
cd services/ingestion/binance-vision-service
BINANCE_VISION_DATABASE_URL='postgresql://postgres:postgres@localhost:15432/market_data' \
python3 -m src collect \
  --dataset crypto.data.futures.um.bookDepth \
  --symbols BTCUSDT \
  --no-csv \
  --emit-interval 5
```

---

## 4) 落盘策略（你必须做的一个选择）

### 4.1 默认建议：`--no-files`（只入库，不保留 ZIP）

- 优点：磁盘压力可控；“全量”可长期跑
- 缺点：你只保留可追溯的元数据（sha256/row_count/min/max），不保留原始 ZIP

### 4.2 如果你坚持保留 ZIP

- 不要指望本机磁盘长期扛住 bookTicker 全历史
- 推荐做法：只保留近 N 天 ZIP；更老的 ZIP 迁移到冷存储（NAS/移动盘），`storage.files.meta.local_path` 仍可作为证据链指针

---

## 5) 已知风险与应对

- **404 垃圾污染**：不要从 2019 盲跑；用“分段推进 + 连续 404 截止”策略。
- **离线场景**：当前 `--local-only` 仅 trades 支持；bookDepth/bookTicker 若要离线全量导入，建议后续补齐 `--local-only`（避免每个文件都去探测 CHECKSUM/HEAD 超时）。
- **浮点精度**：book 系列表为 `DOUBLE`（成本更低）；若你需要“精确对账/财务口径”，应在派生层或单独表做精度治理（不要用 raw 表当精确真相）。
