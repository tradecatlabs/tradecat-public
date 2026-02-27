# CONTEXT - 现状与风险图谱

> 任务编号：0003

## 现状追溯（运行库 + 仓库证据）

### 1) 运行库里 CM trades 仍是旧结构（且与 UM 新表不一致）

- 运行库：`localhost:15432/market_data`
- 表：`crypto.raw_futures_cm_trades`
- 证据（你可复现）：
  - `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_futures_cm_trades"`
  - 观察点（当前实际）：
    - 列为：`exchange, symbol, id, price(numeric), qty(numeric), quote_qty(numeric), time, is_buyer_maker`
    - PK 为：`(exchange, symbol, time, id)`
  - 行数目前为 0：
    - `SELECT COUNT(*) FROM crypto.raw_futures_cm_trades;`

结论：**如果直接照 UM 的新 writer（ids+DOUBLE）去写 CM，会报“列不存在/类型不匹配”。**

### 2) 仓库 DDL 已是“目标结构”，但由于 IF NOT EXISTS 无法修正既有表

- `assets/database/db/schema/009_crypto_binance_vision_landing.sql` 已将 `crypto.raw_futures_um_trades` 定义为 ids+DOUBLE，并用 `LIKE crypto.raw_futures_um_trades` 创建 CM 占位。
- 但运行库里 CM 表是历史遗留创建的旧结构，因此必须单独迁移（drop/recreate 或 rename-swap）。

### 3) 采集卡片仍是占位（未实现）

- 实时：`services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/cm/trades.py` 目前 `NotImplementedError`
- 回填：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/cm/trades.py` 目前 `NotImplementedError`

## 约束矩阵（必须遵守）

- **只用 ccxt/ccxtpro**；实时必须 WS 优先，没 WS 才 REST。
- **字段对齐官方**：每个 CSV 对应一张 raw 表；字段必须能从官方/实时源补齐。
- **事实表极简**：不在 trades 表内塞 `file_id/ingested_at/time_ts`；文件追溯走 `storage.*` 与 `crypto.ingest_*`。
- **不动生产配置**：禁止修改 `config/.env`。

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :---: | :--- | :--- |
| CM 表结构漂移导致采集写库直接崩 | High | 报错 `column venue_id does not exist` / 类型不匹配 | 先迁表再上采集；AC 写死 `\\d+` 断言 |
| CM CSV 字段/时间单位与 UM 不一致 | Medium | backfill COPY 报列数不对/时间轴异常 | 先用 curl/zip 抽样确认列序与时间单位；写入 CONTEXT 固化 |
| venue_code 键空间冲突 | High | core.symbol_map active unique 冲突 | 强制 product=`futures_cm` → venue_code=`binance_futures_cm`（CoreRegistry 已支持） |

## 假设与证伪（每条给命令）

1) 假设：Vision 存在 futures/cm trades 数据集  
   - 证伪：`curl -sSfL "https://data.binance.vision/data/futures/cm/daily/trades/" | head`（若目录索引不可用，则用一个已知 symbol 的 ZIP URL 验证）

2) 假设：CM trades CSV 列序与 UM 相同（含 header）  
   - 证伪：下载任意 1 个 ZIP，解压后 `head -n 2 *.csv` 观察 header（符号 TBD）。

3) 假设：TimescaleDB 已启用且可建 integer hypertable  
   - 证伪：`psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"`（只读环境可用 `SELECT extname FROM pg_extension;`）

