# CONTEXT

## 1) 现状（证据来自仓库扫描）

### 1.1 `libs/` 当前结构同时承载“代码 + 数据 + 外部仓库”

目录（来自 `find libs -maxdepth 2 -type d`）：

```text
libs/
  common/                # 可 import 的共享代码包（存在 __init__.py）
  database/              # SQLite/DDL/CSV/服务持久化文件路径根
  external/              # 多个第三方仓库镜像（非本仓库业务代码）
```

关键事实：`libs/` 被当成 Python 包路径使用（存在 `libs/__init__.py`，且仓库中存在 `import libs...` 的代码引用）。

### 1.2 `libs/common` 存在真实 import 依赖（重命名会直接炸 import）

已观测到的 import/引用（来自 `rg -n "import libs|from libs"` 扫描）：

- `services/compute/ai-service/scripts/start.sh:68`（示例：`from libs.common.utils.gemini_client ...`）
- `services/compute/ai-service/src/llm/client.py:56`（示例：`from libs.common.utils.LLM客户端 ...`）
- `libs/common/utils/LLM客户端.py:11`（示例：`from libs.common.utils.路径助手 ...`）

结论：`libs/` 的整体重命名不是“路径替换”这么简单，而是会影响 Python import 语义与运行时 `sys.path` 注入逻辑。

### 1.3 `libs/database` 路径已成为“配置/脚本/文档真相源”的一部分（必须统一迁移口径）

已观测到的典型硬编码路径引用（来自 `rg -n "libs/"` 扫描）：

- `config/.env.example:458`：`INDICATOR_SQLITE_PATH=libs/database/services/telegram-service/market_data.db`
- `scripts/signal_correlation_analysis.py:31-32`：默认指向 `libs/database/services/signal-service/*`
- `scripts/init.sh:139`：创建 `libs/database/services/telegram-service`
- `scripts/check_env.sh:424`：检查 `libs/database/services/telegram-service/market_data.db`

结论：只要迁移 `libs/database`，就会触发**配置模板、脚本、文档、运维命令**的连锁变更。

### 1.4 `libs/external` 目前更像“第三方仓库集合”（更适合迁到 `assets/repo`）

已观测到 `libs/external/*` 下包含多个第三方仓库目录（来自 `find libs -maxdepth 2 -type d`）：

- `libs/external/freqtrade-develop`
- `libs/external/hummingbot-master`
- `libs/external/zipline-main`
- ……

且当前扫描未发现显式 `libs/external` 的硬编码引用（`rg -n "libs/external"` 输出为空）。

结论：**先迁 `libs/external` → `assets/repo` 是最稳的第一步**。

## 2) 约束矩阵

| 约束 | 说明 | 影响 |
| :-- | :-- | :-- |
| 兼容性优先 | 现有服务必须继续可启动/可跑 | 必须有兼容层或分阶段 |
| 可回滚 | 任一步失败可 100% 回退 | 需要 checkpoint + 原子提交 |
| 不触碰业务逻辑 | 只做路径/入口治理 | 只允许“引用替换/兼容层” |
| 多入口运行 | 顶层脚本 / 单服务脚本 / systemd | 需要覆盖多种启动方式验证 |

## 3) 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :-- | :-- | :-- | :-- |
| Python import 断裂 | High | `ModuleNotFoundError: libs` | Stage 2 引入兼容层（symlink 或 re-export） |
| 路径硬编码漏改 | High | 启动时报 “file not found: libs/database/...” | Stage 0 全仓库盘点 + `rg` gate |
| symlink 在部署环境失效 | Medium | 部署到不保留 symlink 的环境 | 优先选择 Python 兼容包方案（无 symlink 依赖） |
| 外部仓库体积过大导致操作慢 | Low | `git status`/CI 慢 | Stage 1 迁移时仅 `git mv`，不改内容 |

## 4) 假设与证伪（执行 Agent 必须逐条验证）

- 假设 A：执行环境允许创建 symlink（Linux/WSL 默认允许）  
  - Verify: `ln -s /tmp /tmp_symlink_test && test -L /tmp_symlink_test`
- 假设 B：仓库内所有 `libs/` 引用均可通过 `rg -n "libs/"` 捕获  
  - Verify: `rg -n "libs/" -S . | wc -l`（并抽样检查 20 条）
- 假设 C：`libs/external` 当前无运行时依赖（仅做资料/镜像）  
  - Verify: `rg -n "libs/external" -S services scripts config docs | wc -l` 应为 0

