# CONTEXT

## 现状（已确认的证据）

- CLI repair 目前只支持 UM：
  - `services/ingestion/binance-vision-service/src/__main__.py:105-113` 的 `repair --dataset choices` 仅有 `crypto.repair.futures.um.trades`
  - `services/ingestion/binance-vision-service/src/__main__.py:266-286` 仅分支到 `src.collectors.crypto.repair.futures.um.trades.repair_open_gaps`
- 当前仅存在 UM repair 代码目录：
  - `services/ingestion/binance-vision-service/src/collectors/crypto/repair/futures/um/trades.py`
- 治理表 DDL 将 watermark/gap 的时间单位注释为 epoch(ms)：
  - `libs/database/db/schema/012_crypto_ingest_governance.sql:31-53`
- Spot realtime 的 gap 插入使用 ms（REST since 也使用 ms）：
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data/spot/trades.py:390-426`
- 但 Spot 的 watermark 更新当前写入的是 raw 行的 `time`（epoch(us)），与治理表“ms 口径”漂移：
  - `services/ingestion/binance-vision-service/src/collectors/crypto/data/spot/trades.py:258-271`

## 为什么这是硬伤（会咬人）

- repair 只覆盖 UM ⇒ CM/Spot 一旦 gap 积累，只能手工跑 backfill 或临时脚本，不可持续。
- watermark 口径漂移 ⇒ 任何依赖 watermark 的增量逻辑（repair/回放/巡检）都会出现单位误用：轻则漏拉/重复，重则误判缺口范围。

## 约束

- 实时必须 ccxtpro，WS 优先；历史补齐走 Binance Vision ZIP（download/backfill）。
- 不触碰 `config/.env`。
- 不把过程字段塞进事实表（事实表保持纯粹）。

