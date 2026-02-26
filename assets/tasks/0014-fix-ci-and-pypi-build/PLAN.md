# PLAN

## 0) 目标与策略

核心原则：**先恢复“可持续迭代”的最小闭环**，再谈全面代码质量。

## 1) 方案对比

### 方案 A：CI ruff 收敛到 `E,F`（推荐，最快恢复绿）

**做法**
- 把 `.github/workflows/ci.yml` 的 ruff 命令从“默认全规则集”收敛为 `--select E,F`（仍保留 `--ignore E501,E402`）。
- 同步修掉 `services/**` 内所有 `E,F` 级别错误（约 21 条，含 `F401/F821/F601/E721`）。

**Pros**
- 最小改动即可让 CI 恢复稳定绿。
- `E,F` 属于“明显 bug/语法/未定义名/重复键”级别，修复收益高、风险低。

**Cons**
- 未覆盖格式/现代化类型/导入排序等更强约束；需要后续逐步增强。

### 方案 B：修全量 ruff（不推荐作为本任务第一阶段）

**做法**
- 直接对 `services/**` 全量跑 `ruff check --fix` + `ruff format`，并补齐剩余不可自动修复项。

**Pros**
- 一次性把 lint 基线拉满。

**Cons**
- 改动面极大（可能上千文件），审阅/回滚成本高；且对运行链路回归压力大。

**结论**：本任务选择 **方案 A**，并在 `TODO.md` 里留出“增强 lint”作为 P2。

## 2) PyPI/包结构决策

### 方案 A：补齐最小 `src/tradecat/**`（推荐）

目标：让 `pypi-ci.yml` 能完成 lint/test/build/import，且不引入对 `services/**` 的硬依赖。

实现要点：
- `src/tradecat/__init__.py`：导出 `Data/Indicators/Signals/AI/__version__`（可先做轻量 facade / placeholder）。
- `src/tradecat/cli.py`：提供 `main()`，至少支持 `--help`。
- 不要在导入时触发数据库/网络依赖（否则 PyPI import smoke 会不稳定）。

### 方案 B：禁用/移除 pypi-ci/pypi-publish（不推荐）

会破坏既有发布流程，也让 `pyproject.toml` 的 packaging 元信息变成“假配置”。

**结论**：本任务选择 **方案 A**。

## 3) 数据流与执行流（ASCII）

```text
           ┌──────────────┐
           │  assets/repo  │  (第三方镜像仓库，禁止被 pytest/ruff 扫到)
           └──────┬───────┘
                  │
pytest discovery  │   ruff check (services/)
should ignore     │   should be E,F only
                  ▼
           ┌──────────────┐
           │     tests/    │  (仅此为 root pytest 扫描入口)
           └──────────────┘

PyPI CI:
  lint/test/build → 只依赖 src/tradecat/** + tests/**
```

## 4) 原子变更清单（文件级）

执行 Agent 将在以下区域修改（按最小集合）：

- `.github/workflows/ci.yml`：收敛 ruff 命令到 `E,F`
- `services/**`：修复 `E,F` 级别错误（少量文件）
- `src/tradecat/**`：新增最小包骨架与 CLI
- `pyproject.toml`：对齐 packaging 配置（若与实际不一致）
- `README.md` / `AGENTS.md`：补齐“包/CLI”与“CI 基线”说明（如确有必要）

## 5) 回滚协议

1. 若 CI 变红：先回滚 `.github/workflows/ci.yml` 的变更，恢复旧 lint 逻辑。
2. 若 PyPI build/import 失败：回滚 `src/tradecat/**` 与 `pyproject.toml` 的 packaging 变更。
3. 若服务运行受影响：回滚 `services/**` 的 `E,F` 修复提交（这些修复应尽量保持行为不变）。

