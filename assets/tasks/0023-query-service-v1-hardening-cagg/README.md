# 任务门户：query-service-v1-hardening-cagg

## Why（价值，100字内）

把 api-service 真正落成“稳定数据契约层（Query Service / Data API）”：补齐期货指标高周期聚合表（`*_last`）避免长期缺表；让消费层只依赖 `/api/v1/*` 契约端点；统一 UTC 时间口径与健康探测噪音，形成可长期运维的发布闭环。

## In Scope（范围）

- **服务器同步与冒烟**：把本地 `origin/develop` 最新 api-service 部署到服务器并通过关键 curl 验证（`missing_table/capabilities/cards/dashboard`）。
- **补齐期货高周期聚合**：在 LF Timescale 库执行既有 DDL `assets/database/db/schema/007_metrics_cagg_from_5m.sql`，并完成首次 refresh/backfill，生成：
  - `market_data.binance_futures_metrics_{15m,1h,4h,1d,1w}_last`
- **完成 0020 的 P1**：输出类型/单位标准化；更新 `services/consumption/api-service/docs/API_EXAMPLES.md` 与真实行为对齐。
- **推进 0017（消费层只走 /api/v1）**：补齐必要的 v1 wrapper（例如 OHLC），迁移 vis-service 等消费侧移除 `/api/futures/*` 依赖，并用 `scripts/verify.sh` 门禁 enforce。
- **清理 OTHER 健康噪音**：`QUERY_PG_OTHER_URL` 未配置时，不再在 `/api/v1/health|capabilities` 的 sources 中报 `missing_env`。
- **统一 scheduler UTC 口径**：修复 `timestamp without time zone` 的比较/窗口条件，全部以 UTC 为基准，避免“看起来超前/落后”的错觉。
- **全仓门禁**：执行 `./scripts/verify.sh` + 核心服务 `make check`。

## Out of Scope（不做）

- 不新增/改写业务表结构（仅执行仓库已有 DDL；不引入新 schema 设计）。
- 不改 ingestion/compute 的写入链路为 HTTP（写入仍直连 DB）。
- 不做观测/告警体系的大建设（metrics/trace/log 统一先不做，本任务只把契约/数据与时间口径弄“稳”）。

## 执行顺序（强制）

1. `CONTEXT.md`（现状证据与风险）
2. `PLAN.md`（方案选择与回滚）
3. `TODO.md`（逐条执行 + 验证门禁）
4. `ACCEPTANCE.md`（验收断言对照）
5. `STATUS.md`（记录命令与证据）

