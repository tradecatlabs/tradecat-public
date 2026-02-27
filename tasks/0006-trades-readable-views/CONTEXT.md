# CONTEXT

## 已有事实表（物理层）

- `crypto.raw_futures_um_trades`：`time=epoch(ms)`，PK `(venue_id,instrument_id,time,id)`。
- `crypto.raw_futures_cm_trades`：同 UM。
- `crypto.raw_spot_trades`：`time=epoch(us)`，PK `(venue_id,instrument_id,time,id)`。

## 维表映射基础

- `core.venue`：`venue_code` 区分产品（例如 `binance_spot` / `binance_futures_cm`）。
- `core.symbol_map`：以 `[effective_from,effective_to)` 表示映射窗口；active 唯一性已加固（partial unique index）。

## 当前痛点

- 查询必须手动：
  - 时间单位转换（ms/us → timestamptz）
  - ids → `venue_code/symbol` 的 join
- 且如果 join 不写“只取 1 条”，会出现行数放大/随机挑选的问题。

