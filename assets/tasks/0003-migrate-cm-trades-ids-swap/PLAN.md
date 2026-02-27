# PLAN - 架构决策与落地路径

> 任务编号：0003

## 目标

把 futures CM trades 从“占位/漂移状态”升级为与 UM trades 对称的成熟链路：
- 表结构：ids+DOUBLE + integer hypertable + compression
- 写入：幂等（主键去重），可回填，可实时
- 维表：产品键空间不冲突（`binance_futures_cm`）

## 方案对比

### 方案 A（推荐）：rename-swap 迁移（空表也按同一套路）

- 做法：
  1) 将现表改名为 `_old`
  2) 创建新表为目标结构（同 UM）
  3) 若旧表有数据：通过 core 映射回迁到新表（本环境目前为 0 行，可跳过）
  4) 设置 hypertable/压缩/now_func
  5) 验收通过后：可选择保留 `_old`（短期回滚）或删除
- Pros：通用、可回滚、对“未来已落数据”的场景也安全
- Cons：步骤略多

### 方案 B：直接 DROP/CREATE（仅适用于当前空表）

- Pros：最快
- Cons：一旦未来已有数据就不可用；也不利于形成固定迁移范式

选择：**方案 A**（把“迁移套路”固化，避免未来重复踩坑）。

## 逻辑流图（数据流）

```text
ccxtpro WS (watchTrades)  --->  parse（字段对齐）  --->  RawFuturesCmTradesWriter  --->  crypto.raw_futures_cm_trades
            |                                                       |
            +--> gaps(open) ----------------------------------------+

Vision ZIP (daily/monthly) ---> checksum verify ---> COPY tmp ---> INSERT ... ON CONFLICT ... ---> crypto.raw_futures_cm_trades
            |                                     |
            +--> storage.files/import_* 审计 ------+
```

## 原子变更清单（文件级）

- DB：
  - 新增一个迁移脚本（建议 `assets/database/db/schema/014_crypto_futures_cm_trades_ids_swap.sql`），实现 rename-swap + hypertable/compress policy。
- Writers：
  - 新增 `services/ingestion/binance-vision-service/src/writers/raw_futures_cm_trades.py`（对齐 UM 的 writer 形态）。
- Collectors（realtime/backfill）：
  - 实现 `services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/cm/trades.py`
  - 实现 `services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/cm/trades.py`

## 回滚协议

1) 迁表后写库失败  
   - 立刻把 `_old` rename 回原表名（swap back），并停止 CM 采集。
2) 回填导入发现 CSV 口径不一致  
   - 回滚 importer 变更；保留新表结构不变（结构可兼容新增列，但本任务不建议扩列）。

