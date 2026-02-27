# 0015 - unify-all-storage-to-postgres

目标：将项目内仍在使用的 SQLite（指标库 `market_data.db`、信号冷却/订阅/历史、Sheets 幂等/快照）**全面迁移到 PostgreSQL**，并以 `DATABASE_URL` 为唯一长期持久化真相源，形成“单 PG”运维口径（可灰度、可回滚）。

## Why（价值，≤100字）

SQLite 作为文件状态库导致：数据源分裂、跨服务一致性差、备份/回放困难、线上排障依赖拷 DB。统一到 PG 后：单点审计、可观测、可扩展、可运维（备份/复制/权限/索引/分区）。

## In Scope

- 指标派生库：以 `tg_cards` schema 承载原 `market_data.db` 全表（已存在对齐 DDL：`assets/database/db/schema/021_tg_cards_sqlite_parity.sql`）。
- 运行态状态库（信号）：将 `cooldown.db / signal_subs.db / signal_history.db` 迁移到 `signal_state` schema，并替换读写路径（不再落本地 `.db`）。
- 运行态状态库（Sheets）：将 `idempotency.db`（sent_keys）迁移到 `sheets_state` schema，并移除对本地 SQLite 幂等库的强依赖。
- API/Telegram/Sheets/AI 等消费端：统一从 PG 读取（按 `INDICATOR_READ_SOURCE=pg`/默认策略）。
- 迁移工具链：提供“SQLite → PG 一次性迁移脚本 + 校验脚本 + 回滚策略（灰度/双写/可切换）”。
- 文档同步：更新 README/运维手册/架构图，明确“PG 为唯一真相源”的口径。

## Out of Scope

- 不在本任务内重写 Timescale/采集链路的表结构（仅统一持久化与读写来源）。
- 不对 `assets/repo/**` 第三方仓库做任何改动或清理（它们可能包含 sqlite 依赖与示例 `.db`）。
- 不做业务指标/信号算法重构（仅替换存储后端与读写路径）。

## 阅读与执行顺序（必须严格遵守）

1. `CONTEXT.md`：现状证据、约束与风险
2. `PLAN.md`：技术选型、数据流与回滚协议
3. `ACCEPTANCE.md`：验收口径（含边界场景）
4. `TODO.md`：逐项执行（每步必须跑 Verify）
5. `STATUS.md`：记录证据与状态迁移

