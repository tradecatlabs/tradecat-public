# 0014 - fix-ci-and-pypi-build

目标：在 `assets/` 迁移完成后，把仓库恢复到“可持续迭代”的最小闭环：**CI 绿、pytest 可用、PyPI 构建/导入可用**。

## In Scope

- 修复 `.github/workflows/ci.yml` 的 ruff lint 失绿（最小可行：先收敛到 `E,F` 级别的语法/常识错误）。
- 修复 pytest discovery 误扫 `assets/repo/**` 导致 collection 崩溃（确保只跑 `tests/`）。
- 修复 PyPI 相关工作流的结构性断裂：补齐 `src/tradecat/**`（最小可导入的包骨架 + `tradecat` CLI 入口）。
- 建立“可执行的验证命令集”：本地一键复验（lint / tests / build / import）。

## Out of Scope

- 全量修复 `services/**` 的全部 ruff 规则（例如 `UP/I/B/C4` 等 2000+ 项）。本任务只做“让 CI 恢复可用”的最小集。
- 重构服务架构、重写指标/信号/看板业务逻辑。
- 引入 Docker/K8s 部署体系（仓库当前无 Dockerfile 体系）。

## 执行顺序（强制）

1. 先读 `CONTEXT.md`（理解当前 CI 的真实失败原因与触发面）。
2. 按 `PLAN.md` 做决策（选定 lint 策略与 packaging 策略）。
3. 严格按 `TODO.md` 从 P0 到 P2 执行并逐项验收。
4. 每完成一个阶段更新 `STATUS.md`（写入命令输出摘要）。

