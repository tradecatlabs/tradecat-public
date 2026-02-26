# PLAN - 架构决策与落地路径

> 任务编号：0004

## 目标

把 spot trades 做成与 UM trades 同风格的“原子事实表”：
- 表：短主键（ids）、固定宽度（DOUBLE/BOOLEAN/BIGINT）、可压缩（Timescale）
- 链路：实时 WS + Vision 回填双路径，幂等去重
- 治理：storage 审计 + ingest_runs/gaps/watermark

## 关键设计决策：time 存什么单位？

### 方案 A（推荐）：time=epoch(us)（严格保留官方精度）

- Pros：
  - 与 Vision spot CSV 完全一致（最小语义漂移）
  - 不丢精度（对于微观结构/撮合级回测更友好）
- Cons：
  - 实时 ccxtpro 一般只给 ms，需要做 `ms*1000` 的转换（会出现“伪 us”但仍单调）
  - Timescale integer hypertable 需要 `unix_now_us()` 与 `integer_interval=86400000000`

### 方案 B：time=epoch(ms)（统一全库）

- Pros：全库统一 ms，少一套 now_func/interval
- Cons：Vision spot 的 us 精度丢失，且“对齐官方字段”不再严格成立

选择：**方案 A**（对齐官方优先；统一单位可以在查询 view/下游派生层解决）。

## 迁移策略

由于运行库 spot 表目前为 0 行，仍建议按固定套路做 rename-swap：
1) `ALTER TABLE crypto.raw_spot_trades RENAME TO raw_spot_trades_old;`
2) 创建新 `crypto.raw_spot_trades`（目标结构）
3) 重新设置 hypertable/压缩 policy
4) 验收通过后决定是否删除 `_old`

## 原子变更清单（文件级）

- DB：
  - 新增迁移脚本（建议 `libs/database/db/schema/015_crypto_spot_trades_fact_table.sql`）
- Writers：
  - 新增 `services/ingestion/binance-vision-service/src/writers/raw_spot_trades.py`
- Collectors：
  - 实现 `services/ingestion/binance-vision-service/src/collectors/crypto/data/spot/trades.py`
  - 实现 `services/ingestion/binance-vision-service/src/collectors/crypto/data_download/spot/trades.py`

## 回滚协议

1) spot 新表落地后采集写库失败  
   - 停止 spot 采集；把 `_old` rename 回原表名；回滚 writer/collector 变更。

