# 0002 - migrate-um-trades-ids-swap

## 核心价值（Why we do this）

把现网 `crypto.raw_futures_um_trades` 从旧结构（`exchange/symbol + NUMERIC`）迁移到新结构（`venue_id/instrument_id + DOUBLE`），与当前采集写库代码一致，降低索引体积与写入放大，并保留可回滚路径（rename-swap）。

## In Scope（做什么）

- 目标库内完成 `crypto.raw_futures_um_trades` 的 **新表构建 → 分批回迁 → 对账 → rename-swap → 回滚保留**。
- 初始化/补齐 `core.venue/core.instrument/core.symbol_map`，让旧数据可稳定映射到 `instrument_id`。
- 确认 Timescale integer hypertable、压缩设置、policy、主键去重语义在切换后仍正确。

## Out of Scope（不做什么）

- 不修改采集器/写库代码（本任务只做 DB 侧迁移与切换）。
- 不创建派生层物理表（agg/klines/*Klines 等）。
- 不修改 `config/.env`；不删除 `libs/database/` 下任何文件。

## 阅读/执行顺序（强制）

1. `CONTEXT.md`
2. `PLAN.md`
3. `ACCEPTANCE.md`
4. `TODO.md`
5. `STATUS.md`

