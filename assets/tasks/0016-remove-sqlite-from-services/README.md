# 任务门户：remove-sqlite-from-services

## Why（价值）

当前仓库的“运行态”已经基本转向 PostgreSQL（`tg_cards` / `signal_state` / `sheets_state`），但服务侧仍残留 SQLite 时代的测试、默认字段值与文档映射，且部分服务目录仍存在历史 `.db` 文件。这会造成误判、引导错误运维口径，并让后续“单 PG”治理反复返工。本任务目标是：**服务侧彻底不依赖 SQLite**，将 SQLite 限定为“迁移工具/历史工件”，并为 CI/verify 提供明确的验收口径。

## In Scope（范围）

- 逐服务清理 SQLite 残留（代码/测试/文档/运行态遗留 `.db`）：
  - `services/consumption/api-service`
  - `services/consumption/sheets-service`
  - `services/consumption/telegram-service`
  - `services/consumption/vis-service`
  - `services/compute/ai-service`
  - `services/compute/signal-service`
  - `services/compute/trading-service`
- `services/consumption/nofx-dev`：
  - 明确其“预览外部镜像”定位（非核心链路），并确保不被“核心服务去 SQLite”的验收扫描误伤。
  - 如需“严格全仓去 SQLite”，提供单独的迁移/移除路径（P2）。
- 更新相关文档口径（服务 README / 关键设计文档）以匹配现状：运行时只依赖 PG，SQLite 仅保留为迁移工具或外部镜像自用。
- 收敛验收命令：提供可执行的 `rg/find/pytest/make` 验证步骤，确保“无残留可见”。

## Out of Scope（不做）

- 不改动 PostgreSQL 已落地的 schema / 数据（例如 `tg_cards.*` 的表结构与历史数据不重写）。
- 不删除迁移脚本：`scripts/migrate_sqlite_*` / `scripts/sync_market_data_to_rds.py` 仍可保留用于历史回放或外部库导入。
- 不重构 `services/compute/fate-service`（其自用 `bazi.db` 不在本任务范围）。
- `nofx-dev` 的“从 SQLite 迁移到 PG”属于独立项目级重构，默认不在 P0/P1（见 PLAN 的 P2 备选）。

## 执行顺序（强制）

1. `CONTEXT.md`（现状与证据）  
2. `PLAN.md`（方案选择与改动路径）  
3. `TODO.md`（可执行清单）  
4. `ACCEPTANCE.md`（验收口径）  
5. `STATUS.md`（记录执行证据）

