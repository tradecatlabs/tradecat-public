# ACCEPTANCE - 精密验收标准

> 任务编号：0002  
> 目标：让 **运行库** 的 `crypto.raw_futures_um_trades` 与 **仓库新 DDL + 新写库代码** 一致，并且可回滚。

## A. Happy Path（成功路径）

### A1) 表结构切换完成（正式表名不变）

- 断言
  - `\\d+ crypto.raw_futures_um_trades` 显示列为：
    - `venue_id BIGINT`
    - `instrument_id BIGINT`
    - `id BIGINT`
    - `price/qty/quote_qty DOUBLE PRECISION`
    - `time BIGINT`
    - `is_buyer_maker BOOLEAN`
  - PK 为：`(venue_id, instrument_id, time, id)`

### A2) Timescale hypertable 与压缩配置正确

- 断言
  - `timescaledb_information.hypertables` 中存在 `crypto.raw_futures_um_trades`
  - `compression_enabled = true`
  - `primary_dimension = time` 且类型为 `bigint`
  - `set_integer_now_func(...)` 已设置为 `crypto.unix_now_ms()`

### A3) 数据一致性（迁移前后不丢不重）

- 断言（至少满足）
  - 旧表（swap 后的 `*_old`）与新表在同一窗口内 `COUNT(*)` 一致（按 symbol/日窗口抽样）
  - 新表不存在 “unmapped rows”（即 `venue_id/instrument_id` 不能为空；且每个 symbol 能在 `core.symbol_map` 找到映射）

### A4) 写库烟囱测试（不再报列不存在）

- 断言（二选一即可）
  - 运行一次最小 backfill（单日、单 symbol）能写入成功；或
  - 用 `INSERT` 构造 1 行测试数据能成功写入（需先拿到对应 `venue_id/instrument_id`）

---

## B. Edge Cases（至少 3 个边缘路径）

### B1) 可重复执行（幂等）

- 断言
  - 迁移脚本重复跑一次不会重复造数据（PK + ON CONFLICT 保证），并且不会重复造 `core.symbol_map` 记录（或有明确的治理策略）

### B2) 映射缺失时必须失败并暴露证据

- 断言
  - 若某个 (exchange,symbol) 无法构建映射：迁移必须停止，并输出具体的 unmapped 列表（不能静默跳过）

### B3) 压缩窗口与 UPDATE 的硬约束被写死

- 断言
  - 任务文档明确：回填/修复使用 `ON CONFLICT DO UPDATE` 只能发生在“压缩策略生效前”的窗口；超过窗口必须走显式例外流程（decompress → update → recompress）或禁止 UPDATE。

---

## C. Anti-Goals（禁止性准则）

- 不允许直接 `ALTER TABLE crypto.raw_futures_um_trades ...` 在原表上做大规模类型转换（高锁/高风险、难回滚）。
- 不允许在验收完成前删除旧表（必须保留 `*_old` 作为回滚与审计对照）。

