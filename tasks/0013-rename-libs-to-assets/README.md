# 0013 - rename-libs-to-assets

目标：在不破坏现有运行链路的前提下，将仓库内目录语义从 `libs/` 逐步迁移为 `assets/`，并将 `libs/external` 明确为第三方仓库镜像目录：`assets/repo`。

> 重要：这是一次**高影响面的目录重构**。必须按阶段推进，且每一步都要可验证、可回滚。

## Why（价值）

- `libs/` 目前同时承担“可 import 的共享代码包（`libs/common`）”与“资源/数据目录（`libs/database`、`libs/external`）”两类职责，语义混乱、扩展成本高。
- 将第三方仓库镜像统一收敛到 `assets/repo`，更贴近“只读依赖/资料库”的本质，减少误改风险。
- 为后续做“依赖治理/体积治理/许可证扫描/仓库瘦身”铺路。

## In Scope

- 阶段化迁移（默认推荐）：
  - Stage 1（低风险）：`libs/external` → `assets/repo`，并修正所有路径引用。
  - Stage 2（高风险，带兼容层）：`libs/` → `assets/`，同时保留兼容期策略（symlink 或 Python re-export）。
- 全仓库引用盘点（import/path/systemd/docs），形成“必改清单”。
- 更新文档与配置模板中的路径口径（尤其是 `.env.example`、脚本里的默认路径）。
- 每阶段提供可执行的回滚协议。

## Out of Scope

- 修改任何外部仓库镜像内容（`libs/external/*` / `assets/repo/*` 下的第三方项目）。
- 改变数据库 schema / DDL 内容（仅允许路径迁移、引用更新）。
- 顺手重构业务逻辑（非本任务目标）。

## 执行顺序（强制）

1. 读 `CONTEXT.md`（现状与风险）
2. 读 `PLAN.md`（方案与取舍）
3. 按 `TODO.md` 执行（逐项验证）
4. 对照 `ACCEPTANCE.md` 验收
5. 更新 `STATUS.md`（留证据）

