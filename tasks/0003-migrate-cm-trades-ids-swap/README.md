# 0003 - migrate-cm-trades-ids-swap

## 核心价值（Why we do this）

让 `crypto.raw_futures_cm_trades` 与 UM trades 一样成为“短主键、可压缩、可幂等”的原子事实表，避免未来 CM 采集落库时因旧列（`exchange/symbol + NUMERIC`）直接写崩，并为后续多市场/多产品扩展打底。

## In Scope（做什么）

- **DB 结构迁移**：把运行库现有的 `crypto.raw_futures_cm_trades` 从旧结构迁移到新结构（`venue_id/instrument_id + DOUBLE + time(ms)`），并保持 Timescale integer hypertable + 压缩策略一致。
- **采集链路补齐**：补齐 Futures CM trades 的两条链路（实时 WS 优先 + Vision ZIP 回填），实现与 UM trades 对称的“采集卡片”。
- **维度字典化**：复用 `CoreRegistry`，保证 CM 写入使用 `venue_code=binance_futures_cm`（避免与 futures_um/spot 同名 symbol 撞车）。
- **验收与回滚**：提供可执行的验收断言与可回滚迁移路径（rename-swap/保留旧表）。

## Out of Scope（不做什么）

- 不实现 CM 的 `metrics/bookTicker/bookDepth`（本任务只做 trades）。
- 不创建派生层物理表（aggTrades/klines/*Klines）。
- 不修改 `config/.env`（只读）。

## 阅读/执行顺序（强制）

1. `CONTEXT.md`
2. `PLAN.md`
3. `ACCEPTANCE.md`
4. `TODO.md`
5. `STATUS.md`

