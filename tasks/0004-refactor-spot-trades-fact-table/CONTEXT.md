# CONTEXT - 现状与风险图谱

> 任务编号：0004

## 现状追溯（运行库 + 仓库证据）

### 1) 运行库 spot trades 仍是 legacy 表结构（与“事实表极简”哲学冲突）

- 表：`crypto.raw_spot_trades`
- 证据（可复现）：
  - `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_spot_trades"`
  - 观察点（当前实际）：
    - 存在 `file_id / symbol / time_ts / ingested_at`
    - price/qty/quote_qty 为 `numeric(38,12)`
    - PK 为 `(symbol, time_ts, id)`
    - 存在默认 `time_ts` 索引（Timescale 默认行为）
  - 行数目前为 0：
    - `SELECT COUNT(*) FROM crypto.raw_spot_trades;`

结论：**该表与 UM trades 的成熟结构不一致，且 spot 采集卡片一旦落地，必然需要先改表。**

### 2) spot 采集卡片目前仍为占位

- 实时：`services/ingestion/binance-vision-service/src/collectors/crypto/data/spot/trades.py` → `NotImplementedError`
- 回填：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/spot/trades.py` → `NotImplementedError`

### 3) spot trades 的“样本事实”与 UM 不同（必须先写死合同）

在 `assets/database/db/schema/009_crypto_binance_vision_landing.sql` 中已有样本事实备注：
- spot CSV：无 header
- spot 时间戳：epoch(us)
- 列序：`id, price, qty, quote_qty, time(us), is_buyer_maker, is_best_match`

这意味着：
- 回填 COPY 不能用 `HEADER true`
- 实时（ccxtpro）默认 timestamp 为 ms，需要转换到 us（例如 `ms*1000`）

## 约束矩阵（必须遵守）

- 实时必须 WS 优先（ccxtpro）；无 WS 才 REST。
- trades 表保持极简：不塞 `file_id/ingested_at/time_ts`。
- 文件追溯必须走 `storage.*`（checksum/row_count/min/max）而不是塞进事实表。
- spot 的键空间必须与 futures_um 分离（`venue_code=binance_spot`）。

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :---: | :--- | :--- |
| time(us) vs time(ms) 混写导致排序/对账异常 | High | spot 表 time 断崖式跳变或重复 | 写死合同：spot 表 time=epoch(us)；实时统一转 us；验收加窗口断言 |
| is_best_match 实时源缺失 | Medium | 解析报错或字段大量 NULL | 字段允许 NULL；backfill 写真实值；实时尽量从 info 提取，取不到则 NULL 并记 meta |
| legacy 表残留索引/列导致写库失败 | High | 报错列不存在/主键冲突语义变 | 迁表前禁止启用 spot 采集；迁表后 AC1/AC2 必须通过 |

## 假设与证伪（每条给命令）

1) 假设：Vision spot trades ZIP 存在 `.CHECKSUM`  
   - 证伪：`curl -sSfL "https://data.binance.vision/data/spot/daily/trades/BTCUSDT/BTCUSDT-trades-2026-02-12.zip.CHECKSUM" | head`

2) 假设：CSV 无 header，列序如上  
   - 证伪：下载并解压任意日度 ZIP：`unzip -p <zip> | head`（或 `head -n 2`）

