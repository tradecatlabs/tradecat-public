# CONTEXT - 现状与风险图谱

> 任务编号：0001

## 现状追溯（基于仓库可见证据）

### 1) 下载校验目前只到“文件可打开 + Content-Length”

- 下载实现：`services/ingestion/binance-vision-service/src/runtime/download_utils.py:29-73`
  - 只校验 `Content-Length`（若存在）与下载大小一致
  - 不涉及 `.CHECKSUM/sha256` 校验
- 回填侧“修复下载”逻辑：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/trades.py:167-196`
  - 仅用 `probe_content_length` + `_zip_has_csv` 决定是否重下
  - **没有**对 “上游替换/代理污染/静默损坏” 提供可信证据链

### 2) 实时侧能发现 gap，但没有“修复闭环”

- gap 发现与记录：`services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/um/trades.py:322-360`
  - stale 触发 REST overlap 补拉，并写入 `crypto.ingest_gaps`（open 工单）
  - **缺失**：一个自动消费 gap 并“对账→关闭”的 repair worker

### 3) storage/core 维度锚点已存在，但未纳入 UM trades 回填链路

- `storage.*` 与 `core.*` DDL：`assets/database/db/schema/008_multi_market_core_and_storage.sql:12-153`
  - `storage.files` 已有 `checksum_sha256/size_bytes/row_count/min_event_ts/max_event_ts` 等字段
  - `storage.file_revisions/import_batches/import_errors` 已可支撑审计与可观测
  - `core.venue/instrument/symbol_map` 已具备“字典化维度键”基础
- `storage.files` 写入器已存在：`services/ingestion/binance-vision-service/src/writers/storage_files.py:47-78`
  - 但 UM trades 的 download/backfill/realtime 链路 **未使用**该写入器

### 4) 旁路治理表存在（不污染事实表）

- 治理 DDL：`assets/database/db/schema/012_crypto_ingest_governance.sql:15-61`
- 写入器：`services/ingestion/binance-vision-service/src/writers/ingest_meta.py:30-121`

---

## 约束矩阵（必须遵守）

- 目录对齐与字段完备：`services/ingestion/binance-vision-service/AGENTS.md`
  - 官方目录结构=数据契约；一个 CSV 数据集=一个采集卡片
  - 事实表只收 Raw/Atomic
  - 实时优先 WS（ccxtpro），无 WS 才 REST
- 配置安全：禁止修改 `config/.env`（只读）
- 事实表污染控制：UM trades 表坚持“极简字段”（不新增 `file_id/ingested_at/time_ts`）

---

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :---: | :--- | :--- |
| 上游文件被替换/代理污染但未察觉 | High | 同一路径重复下载后内容变化但导入仍“成功” | 引入 `.CHECKSUM/sha256`；不一致即失败并写 `storage.import_errors`；必要时写 `storage.file_revisions` |
| gap 记录但不修复导致长期缺数据 | High | `crypto.ingest_gaps` 长期堆积 open | 新增 `repair` worker（消费 gap、补齐、对账、关闭） |
| 审计缺失导致无法复现与追责 | High | 无法回答“这批数据来源哪个 rel_path/sha256” | 回填链路必须写 `storage.files/import_batches/import_errors` |
| 主键 TEXT 导致索引肥、成本爆炸 | Medium | 索引体积接近或超过 heap；写入明显变慢 | 上 v2 表：`venue_id/instrument_id` 字典化；保留 view 兼容查询 |
| checksum 机制实现错误导致误判 | Medium | 大量 false negative（明明正确却判错） | 在落地前先探测 `.CHECKSUM` 格式；提供 `--allow-no-checksum` 逃生阀；单测覆盖 |

---

## 假设与证伪（每条假设都给出可执行命令）

> 说明：本任务默认不阻塞推进；所有“不确定但可验证”的点都在这里列出，执行 Agent 应优先跑这些命令锁定事实。

1) 假设：Binance Vision 提供与 ZIP 对应的 `.CHECKSUM`  
   - 证伪（示例：日度 ZIP）：`curl -sSfL "<BINANCE_DATA_BASE>/data/futures/um/daily/trades/BTCUSDT/BTCUSDT-trades-2026-02-12.zip.CHECKSUM" | head`

2) 假设：`.CHECKSUM` 格式是“sha256 + filename”（单行或多行）  
   - 证伪：对同一 CHECKSUM 跑 `head` 并观察是否包含 zip 文件名

3) 假设：本地 `storage.*` 表已存在（可用）  
   - 证伪：`psql "$DATABASE_URL" -c "\\dt storage.*"`

4) 假设：本地 `crypto.ingest_*` 表已存在（可用）  
   - 证伪：`psql "$DATABASE_URL" -c "\\dt crypto.ingest_*"`

5) 假设：`core.*` 维表已存在（用于 v2 字典化）  
   - 证伪：`psql "$DATABASE_URL" -c "\\dt core.*"`
