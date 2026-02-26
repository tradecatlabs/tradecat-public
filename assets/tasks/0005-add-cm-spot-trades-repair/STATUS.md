# STATUS

Status: Done

## Evidence Log

- CLI repair dataset choices 已补齐：`services/ingestion/binance-vision-service/src/__main__.py`
- CM repair 运行闭环（open → repairing → closed），示例日志见 2026-02-15 执行记录
- Spot repair 运行闭环（open → repairing → closed），示例日志见 2026-02-15 执行记录
- Spot watermark 单位修正：
  - 写入侧已改为 epoch(ms)：`services/ingestion/binance-vision-service/src/collectors/crypto/data/spot/trades.py`
  - 回填侧已改为 epoch(ms)：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/spot/trades.py`
  - 运行库存量 `crypto.ingest_watermark(dataset='spot.trades')` 已从 us 转成 ms（阈值门禁，避免误伤）

## Notes

- 注意：spot 事实表 time=epoch(us) 与治理表 watermark/gaps=epoch(ms) 是“刻意的双口径”：
  - raw：对齐 Vision CSV（us）
  - 治理：对齐 REST since/gap（ms）
