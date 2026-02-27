# 0004 - refactor-spot-trades-fact-table

## 核心价值（Why we do this）

把 spot trades 从“legacy 落库表（file_id + time_ts + NUMERIC）”升级为与你已认可的“原子事实表”形态（ids + DOUBLE + integer hypertable），并补齐 spot 的实时/回填采集卡片，让现货逐笔也能进入同一套可审计、可修复、可压缩的长期运行底盘。

## In Scope（做什么）

- **表结构重构**：将 `crypto.raw_spot_trades` 重构为极简事实表：
  - 维度键：`venue_id, instrument_id`
  - 原子字段：对齐 Vision spot trades 列序（含 `is_best_match`）
  - 时间轴：`time BIGINT`（按 Vision 事实为 epoch(us)，保留 us 精度）
  - Timescale：integer hypertable + compression（与 UM 同风格）
- **采集链路补齐**：
  - 实时：ccxtpro `watchTrades`（WS 优先）→ 字段对齐 → writer 幂等落库
  - 回填：Vision daily/monthly ZIP + `.CHECKSUM` 校验 + storage 审计 → writer 落库
- **维度键空间**：spot 必须使用 `venue_code=binance_spot`（避免与 futures_um 同名 symbol 撞车）。

## Out of Scope（不做什么）

- 不实现 spot 的 `aggTrades/klines`（派生层后置）。
- 不修改 `config/.env`。
- 不做跨交易所统一（只做 Binance Vision 口径）。

## 阅读/执行顺序（强制）

1. `CONTEXT.md`
2. `PLAN.md`
3. `ACCEPTANCE.md`
4. `TODO.md`
5. `STATUS.md`

