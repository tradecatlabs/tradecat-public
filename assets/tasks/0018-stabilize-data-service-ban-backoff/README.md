# 任务门户：stabilize-data-service-ban-backoff

## Why（价值）

data-service 当前会在 Binance 返回 `418 I'm a teapot ... IP banned until ...` 时持续发起 REST 请求，导致 ban 延长、DB 新鲜度持续陈旧，并触发 `start.sh` 守护循环反复自愈重启 `ws` 组件，形成“重启风暴”。这会直接造成 1m K 线与派生指标缺口、资源浪费、以及上游恢复时间不可控。

本任务目标：在不改变核心数据模型的前提下，让采集链路对 ban/限流具备“业内成熟”的退避与自愈行为：**能识别 ban → 全局冷却 → 恢复后再继续**，并避免“自愈反而放大故障”。

## In Scope（范围）

- 修复 `services/ingestion/data-service/src/adapters/ccxt.py`：
  - 统一对 `418/429/banned until` 的识别：即便异常类型是 `NetworkError` 也必须 `parse_ban()` + `set_ban()`
  - 统一退避策略（指数退避 + ban 冷却），避免 busy loop
- 收敛 REST backfill 的并发与请求权重：
  - `collectors/backfill.py` 的 `RestBackfiller(workers=8)` 改为可配置（环境变量）并给出安全默认值
  - 当触发 ban 时，backfill 主动暂停/降速（依赖全局 limiter）
- 让守护自愈逻辑“ban-aware”：
  - `services/ingestion/data-service/scripts/start.sh` 在检测到全局 ban 期间，不应因 DB 新鲜度陈旧而反复重启 ws（重启不会解除 ban）
- 补齐可观测性与运维手册（最小但够用）：
  - 日志中必须能清晰看到：ban 触发时间、ban until、等待时长、恢复时刻、触发源（REST/metrics/ws gapfill）
  - 更新相关 `.env.example`/docs（仅涉及新增可选配置项与解释）

## Out of Scope（不做）

- 不改 Timescale/Postgres schema（不做表结构迁移）
- 不引入新的外部依赖（如 Redis、消息队列）
- 不重写 cryptofeed/WebSocket 实现（仅调整与之交互的退避/自愈）

## 执行顺序（强制）

1. `CONTEXT.md`（现状与证据）
2. `PLAN.md`（方案选择与路径）
3. `TODO.md`（可执行清单）
4. `ACCEPTANCE.md`（验收口径）
5. `STATUS.md`（记录执行证据）

