# ACCEPTANCE

## AC1｜view 存在且可查询

- 验证命令（示例）：
  - `\\dv crypto.vw_futures_um_trades`
  - `SELECT * FROM crypto.vw_futures_um_trades LIMIT 1;`
- 通过条件：view 存在，查询成功。

## AC2｜时间转换正确且不影响物理数据

- 验证：同一行在 view 中：
  - `time`（整数）不变
  - `time_ts_utc = to_timestamp(time/1000.0)`（UM/CM）或 `to_timestamp(time/1000000.0)`（Spot）
  - `time_ts_cn = time_ts_utc AT TIME ZONE 'Asia/Shanghai'`（仅展示）
- 通过条件：UTC 与 UTC+8 显示正确，物理表不新增列。

## AC3｜symbol join 不放大行数

- 验证：`EXPLAIN` 显示 join 使用 LATERAL+LIMIT 1（或等价只取 1 条 as-of 匹配）。
- 通过条件：不会因为 symbol_map 多条记录导致 view 结果重复。

