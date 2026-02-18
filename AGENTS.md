# TradeCat - AI Agent 操作手册

> 本文档面向 AI 编码 Agent，以可执行指令的视角编写，约束与指导 Agent 行为。

---

## 1. Mission & Scope（目标与边界）

### 1.1 允许的操作

- 修改 `services/**/src/` 下的业务代码（按 ingestion/compute/consumption 分层）
- 修改 `config/.env.example` 全局配置模板
- 添加/修改技术指标 (`services/compute/trading-service/src/indicators/`)
- 添加/修改排行榜卡片 (`services/consumption/telegram-service/src/cards/`)
- 修改启动脚本 (`services/*/scripts/`, `scripts/`)
- 更新文档 (`README.md`, `README_EN.md`, `AGENTS.md`)
- 修改 `Makefile`、`pyproject.toml`

### 1.2 禁止的操作

- **禁止修改** `config/.env` 生产配置文件
- **禁止修改** 数据库 schema（除非明确要求）
- **禁止删除** `libs/database/` 下的数据文件
- **禁止修改** `.gitignore` 中已忽略的敏感文件
- **禁止** 大范围重构，除非任务明确要求
- **禁止** 添加未经验证的第三方依赖

### 1.3 敏感区域

| 路径 | 说明 | 操作限制 |
|:---|:---|:---|
| `config/.env` | 生产配置（含密钥） | 只读 |
| `libs/database/services/telegram-service/market_data.db` | SQLite 指标数据 | 只读 |
| `libs/database/services/signal-service/cooldown.db` | 信号冷却持久化 | 只读 |
| `libs/database/services/signal-service/signal_history.db` | 信号触发历史 | 只读 |
| `backups/timescaledb/` | 数据库备份 | 禁止修改 |

> 提醒：服务启动脚本会检查 `config/.env` 权限（需 600/400），不符合直接退出。

---

## 2. Golden Path（推荐执行路径）

### 2.1 最短可复现场景

```bash
# 进入项目根目录
cd /path/to/tradecat

# 1) 初始化：创建各服务 .venv、安装依赖、复制配置模板
./scripts/init.sh

# 2) 填写全局配置（含 BOT_TOKEN / DB / 代理 等）
cp config/.env.example config/.env && chmod 600 config/.env
vim config/.env

# 3) 启动核心服务（ai + signal + telegram + trading）
./scripts/start.sh start
./scripts/start.sh status
```

> 顶层 `./scripts/start.sh` 管理 ai-service / signal-service / telegram-service / trading-service（ai-service 仅做就绪检查，无独立进程）。

### 2.2 按服务手动启动（调试/可选）

```bash
# binance-vision-service（采集，CLI）
cd services/ingestion/binance-vision-service && python3 -m src --version

# trading-service（指标计算）
cd services/compute/trading-service && ./scripts/start.sh start

# signal-service（信号检测）
cd services/compute/signal-service && ./scripts/start.sh start

# telegram-service（Telegram Bot）
cd services/consumption/telegram-service && ./scripts/start.sh start

# api-service（REST API，可选）
cd services/consumption/api-service && ./scripts/start.sh start
```

### 2.3 开发/修改流程

```bash
# 1. 进入对应服务并激活虚拟环境
cd services/compute/trading-service && source .venv/bin/activate

# 2. 修改代码...

# 3. 使用服务级 Makefile
make lint      # 代码检查
make format    # 代码格式化
make test      # 运行测试

# 4. 验证
cd /path/to/tradecat
./scripts/verify.sh

# 5. 若涉及命令/配置/目录变更，同步更新 README.md / README_EN.md / AGENTS.md
```

---

## 3. Must-Run Commands（必须执行的命令清单）

### 3.1 全局脚本

| 命令 | 说明 |
|:---|:---|
| `./scripts/init.sh` | 初始化所有核心服务虚拟环境 |
| `./scripts/init.sh <service>` | 初始化单个服务 |
| `./scripts/init.sh --all` | 初始化全部服务（含可选服务） |
| `./scripts/start.sh start\|stop\|status\|restart` | 核心服务管理 |
| `./scripts/start.sh daemon\|daemon-stop` | 守护进程模式（自动重启崩溃服务） |
| `./scripts/check_env.sh` | 环境检查（Python/依赖/配置/网络/数据库） |
| `./scripts/verify.sh` | 代码验证（ruff + py_compile + i18n） |
| `python scripts/download_hf_data.py` | 从 HuggingFace 下载历史数据并导入 |
| `python scripts/check_i18n_keys.py` | 检查 i18n 翻译键对齐 |
| `python scripts/sync_market_data_to_rds.py` | 增量同步 SQLite `market_data.db` 到 PostgreSQL（RDS/Aurora） |
| `./scripts/export_timescaledb.sh` | 导出 TimescaleDB 数据（默认端口 5433） |
| `./scripts/export_timescaledb_main4.sh` | 导出 Main4 精简数据集（默认端口 5433） |
| `./scripts/timescaledb_compression.sh` | 压缩管理（默认端口 5433） |

### 3.2 Make 快捷命令

| 命令 | 说明 |
|:---|:---|
| `make init` | 初始化所有服务 |
| `make install` | 一键安装（等价 `./scripts/install.sh`） |
| `make start` | 启动所有服务 |
| `make stop` | 停止所有服务 |
| `make status` | 查看服务状态 |
| `make daemon` | 启动守护进程（自动重启） |
| `make daemon-stop` | 停止守护进程 |
| `make verify` | 代码验证 |
| `make clean` | 清理缓存 |
| `make export-db` | 导出 TimescaleDB 数据 |

### 3.3 服务级 Makefile（统一接口）

每个服务都有标准化的 Makefile，支持以下 targets：

```bash
cd services/<layer>/<service-name>

make help        # 显示帮助
make venv        # 创建虚拟环境
make install     # 安装依赖
make install-dev # 安装开发依赖
make clean       # 清理缓存
make reset       # 重建虚拟环境（依赖坏了用这个）
make lock        # 导出当前依赖到 requirements.lock.txt

make lint        # 代码检查 (ruff)
make format      # 代码格式化 (ruff)
make test        # 运行测试 (pytest)
make test-cov    # 运行测试 + 覆盖率
make typecheck   # 类型检查 (mypy)
make check       # 完整检查 (lint + test)
make syntax      # 语法验证（快速）

make run         # 前台运行（调试用）
make start       # 后台启动
make stop        # 停止服务
make status      # 查看状态
```

### 3.4 数据库操作

> **端口说明**：推荐 **LF+HF 双集群**，避免同名表在不同库里结构漂移导致写库崩溃：
> - LF（低频/分时/K线与指标）：`localhost:5433/market_data`（`DATABASE_URL` / `DATA_SERVICE_DATABASE_URL`）
> - HF（高频/原子事实）：`localhost:15432/market_data`（`BINANCE_VISION_DATABASE_URL`）

```bash
# 连接 TimescaleDB（LF）
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data

# 连接 TimescaleDB（HF）
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data

# 查看 K线数据量
SELECT COUNT(*) FROM market_data.candles_1m;

# 连接 SQLite
sqlite3 libs/database/services/telegram-service/market_data.db
```

---

## 4. Code Change Rules（修改约束）

### 4.1 架构原则

- **微服务独立**：每个服务有独立的 `.venv`、`requirements.txt`、`pyproject.toml`、`Makefile`
- **配置统一**：所有配置集中在 `config/.env`，各服务共用
- **数据流向**：`ingestion → TimescaleDB → trading-service → SQLite → telegram/api/sheets → (ai/signal)`

### 4.2 服务清单（7 个）

| 服务 | 分层 | 位置 | 职责 | 入口 |
|:---|:---|:---|:---|:---|
| binance-vision-service | ingestion | `services/ingestion/binance-vision-service/` | Binance Vision Raw 对齐采集（实时 + ZIP 回填） | `src/__main__.py` |
| trading-service | compute | `services/compute/trading-service/` | 指标计算（写入 SQLite） | `src/__main__.py` |
| signal-service | compute | `services/compute/signal-service/` | 信号检测（规则引擎，读库） | `src/__main__.py` |
| ai-service | compute | `services/compute/ai-service/` | AI 分析（telegram 子模块） | `src/__main__.py` |
| telegram-service | consumption | `services/consumption/telegram-service/` | Bot 交互、卡片渲染、订阅管理 | `src/main.py` |
| api-service | consumption | `services/consumption/api-service/` | REST API（只读查询） | `src/__main__.py` |
| sheets-service | consumption | `services/consumption/sheets-service/` | Google Sheets 公共看板同步（卡片→表格） | `src/__main__.py` |

> 低频/分时采集服务：`services/ingestion/data-service/`（兼容链路，不进入默认启动链路，需要时手动运行）。

### 4.3 模块边界

| 服务 | 职责 | 禁止 |
|:---|:---|:---|
| binance-vision-service | 加密货币数据采集、写入 TimescaleDB（Raw 对齐） | 禁止计算指标与写入 SQLite |
| trading-service | 指标计算、写入 SQLite | 禁止直接推送消息/依赖 Telegram |
| signal-service | 信号检测、规则引擎 | 禁止 Telegram 依赖；默认只读业务数据（冷却/历史为例外的持久化） |
| telegram-service | Bot 交互、卡片渲染、订阅管理 | 禁止包含信号检测核心逻辑（规则引擎在 signal-service） |
| ai-service | AI 分析（telegram 子模块） | 禁止承担常驻采集/计算职责（避免与 data/trading 重叠） |
| api-service | REST API 数据查询 | 只读数据库，禁止写入 |
| sheets-service | Google Sheets 看板同步（卡片导出/审计） | 禁止承担指标计算/采集；只做消费层导出与旁路同步 |

> **注意**：telegram-service/signals 模块已解耦，仅保留适配层 (`adapter.py`) 和 UI (`ui.py`)，信号检测逻辑全部在 signal-service 中。
> 冷却持久化：`services/compute/signal-service/src/storage/cooldown.py` 负责将冷却键写入 `libs/database/services/signal-service/cooldown.db`，SQLite 引擎启动时加载，`_set_cooldown()` 同步落盘；公共接口 `get_cooldown_storage()` 供其他模块复用。

### 4.4 依赖添加规则

1. 添加依赖前检查是否已存在
2. 添加到对应服务的 `requirements.txt`
3. 运行 `make lock` 更新 `requirements.lock.txt`
4. 如需系统库（如 TA-Lib），在 README 中说明安装方法
5. 禁止添加未经验证的依赖

### 4.5 兼容性要求

- Python >= 3.10（CI 使用 3.12，pyproject.toml 声明 >=3.9）
- 保持与现有数据库 schema 兼容
- 新增指标需注册到 `indicators/__init__.py`
- 新增卡片需注册到 `cards/registry.py`

---

## 5. Style & Quality（风格与质量标准）

### 5.1 代码风格

- **格式化**：遵循 PEP 8，使用 ruff
- **行长**：120 字符
- **类型注解**：关键函数添加类型注解
- **文档字符串**：公开函数需有 docstring

### 5.2 项目配置（pyproject.toml 统一标准）

所有服务的 `pyproject.toml` 使用统一配置：

```toml
[project]
requires-python = ">=3.12"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
```

### 5.3 命名约定

| 类型 | 约定 | 示例 |
|:---|:---|:---|
| 文件名 | 小写下划线或中文 | `k_pattern.py`, `资金费率卡片.py` |
| 类名 | PascalCase | `KPattern`, `DataProvider` |
| 函数名 | snake_case | `compute_indicators()` |
| 常量 | UPPER_SNAKE | `MAX_WORKERS` |

### 5.4 错误处理

- 使用 `except Exception as e:` 捕获异常并记录日志
- 禁止裸 `except:`
- 关键操作添加超时处理

### 5.5 日志规范

```python
import logging
logger = logging.getLogger(__name__)

logger.info("操作成功: %s", detail)
logger.warning("警告: %s", message)
logger.error("错误: %s", error, exc_info=True)
```

---

## 6. Project Map（项目结构速览）

```
tradecat/
├── config/                         # 统一配置（所有服务共用）
│   ├── .env                        # 生产配置（含密钥，不提交）
│   ├── .env.example                # 配置模板（默认：LF=5433，HF=15432）
│   └── logrotate.conf              # 日志轮转
│
├── scripts/                        # 全局脚本
│   ├── init.sh                     # 初始化脚本
│   ├── install.sh                  # 一键安装
│   ├── start.sh                    # 统一启动脚本
│   ├── verify.sh                   # 验证脚本（ruff + py_compile + i18n）
│   ├── check_env.sh                # 环境检查
│   ├── check_i18n_keys.py          # i18n 翻译键对齐检查
│   ├── download_hf_data.py         # HuggingFace 数据下载
│   ├── signal_correlation_analysis.py # 信号相关性分析（cooldown + PG）
│   ├── sync_market_data_to_rds.py  # SQLite -> PostgreSQL 增量同步
│   ├── export_timescaledb.sh       # 数据导出（默认端口 5433）
│   ├── export_timescaledb_main4.sh # 导出 Main4 精简数据集（默认端口 5433）
│   └── timescaledb_compression.sh  # 压缩管理（默认端口 5433）
│
├── services/                       # 服务分层（采集/计算/消费）
│   ├── ingestion/                  # 采集层：写 TimescaleDB
│   │   ├── binance-vision-service/ # Binance Vision Raw 对齐采集
│   │   └── data-service/           # 低频/分时采集（1m/5m，兼容链路，非默认启动）
│   ├── compute/                    # 计算层：读 PG / 写 SQLite
│   │   ├── trading-service/        # 指标计算（写入 SQLite）
│   │   ├── signal-service/         # 信号检测（规则引擎）
│   │   └── ai-service/             # AI 分析（telegram 子模块）
│   └── consumption/                # 消费层：Telegram/API
│       ├── telegram-service/       # Telegram Bot
│       ├── api-service/            # REST API（可选）
│       └── sheets-service/         # Google Sheets 公共看板同步（可选）
│
├── libs/
│   ├── database/                   # 数据库文件
│   │   ├── db/                     # DDL schema 定义
│   │   ├── csv/                    # CSV 数据
│   │   └── services/
│   │       ├── telegram-service/
│   │       │   └── market_data.db      # 指标数据（Telegram 展示使用）
│   │       └── signal-service/
│   │           ├── cooldown.db         # 冷却状态持久化（防重复推送）
│   │           └── signal_history.db   # 信号触发历史（append-only）
│   ├── common/                     # 共享工具库
│   │   ├── i18n.py                 # 国际化模块
│   │   ├── symbols.py              # 币种管理模块
│   │   ├── proxy_manager.py        # 代理管理器
│   │   └── utils/                  # 工具函数
│   └── external/                   # 外部依赖/数据
│
├── .github/                        # 社区规范与 CI
│   ├── workflows/                  # CI 配置
│   │   ├── ci.yml                  # ruff + py_compile 抽样检查
│   │   ├── pypi-ci.yml             # PyPI CI
│   │   └── pypi-publish.yml        # PyPI 发布
│   ├── CONTRIBUTING.md             # 贡献指南
│   ├── CODE_OF_CONDUCT.md          # 行为准则
│   └── SECURITY.md                 # 安全政策
│
├── artifacts/                      # 构建/测试产物
│   ├── services-archived/          # 历史服务归档区（按需使用）
│   ├── analysis/                   # 分析产物
│   │   └── signal_correlation/     # 信号相关性分析输出
│   ├── coverage/                   # 覆盖率数据
│   ├── dist/                       # 构建输出
│   └── i18n/                       # i18n 编译产物
│
├── cache/                          # 工具缓存
│   ├── pytest/
│   └── ruff/
│
├── docs/                           # 项目文档
│   ├── analysis/                   # 分析文档
│   │   └── signal_correlation.md   # 信号相关性分析说明
│   ├── CHANGELOG.md                # 变更日志
│   ├── COMPETITION_REPORT.md       # 比赛汇报材料
│   ├── MARKETING_PROMO.md          # 宣传材料
│   └── TODO.md                     # 待办清单
│
├── logs/                           # 顶层日志
│   └── daemon.log
│
├── run/                            # 顶层进程状态
│   └── daemon.pid
│
├── Makefile                        # 常用命令快捷方式
├── pyproject.toml                  # 根级项目配置
├── README.md                       # 项目文档（中文）
├── README_EN.md                    # 项目文档（英文）
├── PERFORMANCE_AUDIT_TRADING_SERVICE.md # trading-service Python 性能优化审计报告（静态审计版）
├── TODO.md                         # trading-service 性能优化执行清单
├── AGENTS.md                       # 本文档
└── .python-version                 # Python 版本锁定
```

### 6.1 服务标准化结构

每个服务遵循统一结构：

```
<service>/
├── .python-version         # Python 版本 (3.12)
├── .gitignore              # Git 忽略规则
├── .venv/                  # 虚拟环境（不提交）
├── Makefile                # 服务级 Make 命令
├── pyproject.toml          # 项目配置（含 ruff/pytest/mypy）
├── requirements.txt        # 运行依赖
├── requirements-dev.txt    # 开发依赖
├── requirements.lock.txt   # 锁定依赖
├── src/                    # 源代码
│   ├── __init__.py
│   └── __main__.py         # 入口
├── tests/                  # 测试
│   ├── __init__.py
│   └── conftest.py
├── scripts/
│   └── start.sh            # 启动脚本
└── logs/                   # 日志目录
```

### 6.2 trading-service core 分层（IO/Compute/Storage）

```
services/compute/trading-service/src/core/
├── engine.py               # 流程编排：只管调度与观测
├── io.py                   # 数据读取与缓存装配（只读）
├── compute.py              # 指标计算与并行调度（纯计算）
└── storage.py              # 结果落盘与后处理（只写）
```

边界约束：
- IO 只负责读取与缓存装配，不写库、不计算指标
- Compute 只计算，不做任何数据库读写
- Storage 只负责落盘与后处理，不参与指标计算

---

## 7. Common Pitfalls（常见坑与修复）

### 7.1 TA-Lib 安装失败

```bash
# 先安装系统库
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib && ./configure --prefix=/usr && make && sudo make install
cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# 再安装 Python 包
pip install TA-Lib
```

### 7.2 数据库连接失败

```bash
# 检查端口（LF=5433，HF=15432）
ss -tlnp | grep -E '5433|15432'

# 测试连接（LF）
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data -c "\l"

# 测试连接（HF）
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\l"
```

### 7.3 虚拟环境问题

```bash
# 重建虚拟环境（依赖坏了用这个）
cd services/<layer>/<service>
make reset
```

### 7.4 .env 权限问题

```bash
# 服务启动脚本要求 600 权限
chmod 600 config/.env
```

### 7.5 环境检查

```bash
# 部署前运行环境检查，确保所有依赖就绪
./scripts/check_env.sh

# 检查内容：
# - Python 版本 (3.10+)
# - pip/venv 可用性
# - 虚拟环境完整性
# - config/.env 配置
# - 数据库连接 (pg_isready)
# - 网络连接 (Telegram/Binance API)
# - 磁盘空间
```

### 7.6 日志轮转配置

```bash
# 1. 生成配置文件（替换路径占位符）
cd /path/to/tradecat
sed -e "s|{{PROJECT_ROOT}}|$(pwd)|g" \
    -e "s|{{USER}}|$(whoami)|g" \
    config/logrotate.conf > /tmp/tradecat-logrotate.conf

# 2. 手动执行轮转
sudo logrotate -f /tmp/tradecat-logrotate.conf

# 3. 安装到系统（可选，自动每日执行）
sudo cp /tmp/tradecat-logrotate.conf /etc/logrotate.d/tradecat

# 轮转策略：
# - 核心服务日志：每天或 50MB，保留 14 天
# - 预览服务日志：每天或 50MB，保留 7 天
# - 顶层 logs 目录日志：每天或 20MB，保留 7 天
```

### 7.7 守护进程模式

```bash
# 启动守护进程（自动重启崩溃的服务）
./scripts/start.sh daemon

# 停止守护进程和所有服务
./scripts/start.sh daemon-stop

# 守护策略：
# - 检查间隔：30 秒
# - 最大重试：5 次/5分钟窗口
# - 指数退避：10s → 20s → 40s → ... → 300s (最大)
# - telegram-service 定时重启：每 1 小时一次（临时止血）
# - 超过上限后暂停重启，告警写入 alerts.log
```

### 7.8 端口/双集群（LF/HF）

```bash
# LF（5433）：K线/指标（market_data.*），默认由 DATABASE_URL 承载
# HF（15432）：原子事实（core/storage/crypto.raw_*），由 BINANCE_VISION_DATABASE_URL 承载

# 确认当前使用端口
grep -E "^(DATABASE_URL|DATA_SERVICE_DATABASE_URL|BINANCE_VISION_DATABASE_URL)=" config/.env

# 初始化 DDL（禁止跑 schema/*.sql，必须通过 stacks 入口）
PGPASSWORD=postgres psql -h localhost -p 5433  -U postgres -d market_data -f libs/database/db/stacks/lf.sql
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -f libs/database/db/stacks/hf.sql
```

---

## 8. PR / Commit Rules（提交规则）

### 8.1 Commit Message 规范

```
<type>(<scope>): <subject>

<body>
```

**Type**：
- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `refactor`: 重构
- `chore`: 杂项
- `style`: 代码格式

**示例**：
```
feat(trading): 添加 K线形态检测指标
fix(telegram): 修复排行榜数据加载错误
docs: 更新 README 快速开始指南
chore: standardize project structure for all services
```

### 8.2 提交前检查清单

- [ ] 代码通过 `make lint`
- [ ] 测试通过 `make test`（如有）
- [ ] 相关文档已更新
- [ ] 配置变更已同步到 `config/.env.example`
- [ ] 新依赖已添加到 `requirements.txt` 并 `make lock`

### 8.3 CI 说明

CI（`.github/workflows/ci.yml`）仅执行：
- ruff 静态检查（忽略 E501, E402）
- py_compile 语法检查（前 50 个 .py 文件抽样）

完整测试需本地运行 `./scripts/verify.sh`。

---

## 9. Documentation Sync Rule（文档同步规则）

### 9.1 强制同步

以下变更**必须**同步更新文档：

| 变更类型 | 需更新的文档 |
|:---|:---|
| 新增/修改命令 | README.md, README_EN.md, AGENTS.md |
| 新增/修改配置项 | README.md, README_EN.md, `config/.env.example` |
| 新增/修改指标 | README.md (指标列表) |
| 目录结构变更 | README.md, README_EN.md, AGENTS.md |
| 新增/修改服务 | README.md, README_EN.md, AGENTS.md |

### 9.2 文档更新原则

- 以实时代码为唯一源头
- 不确定的端口、路径、命令**必须**验证后再写入
- 三份文档（README.md、README_EN.md、AGENTS.md）保持同步

### 9.3 设计/运维文档入口（单点索引）

- `docs/analysis/INDEX.md`：分析/设计/落地文档索引（单点真相入口）。
- `docs/analysis/crypto_raw_trades_hardening_runbook.md`：trades 加固 runbook（019 历史一致性、`--force-update` 权限隔离、验收 SQL）。
- `services/ingestion/binance-vision-service/AGENTS.md`：采集服务内硬契约（DDL 真相源、事实表契约、运维加固要点）。

---

## 10. 环境变量参考

所有配置集中在 `config/.env`，详细说明见 `config/.env.example`。

### 10.1 核心配置

| 变量 | 说明 | 示例 |
|:---|:---|:---|
| `DATABASE_URL` | LF（K线/指标）TimescaleDB 连接串 | `postgresql://postgres:postgres@localhost:5433/market_data` |
| `DATA_SERVICE_DATABASE_URL` | data-service 专用 LF 连接串（可选） | `postgresql://postgres:postgres@localhost:5433/market_data` |
| `BINANCE_VISION_DATABASE_URL` | HF（原子事实）连接串（binance-vision 专用） | `postgresql://postgres:postgres@localhost:15432/market_data` |
| `BOT_TOKEN` | Telegram Bot Token | `123456:ABC...` |
| `HTTP_PROXY` | HTTP 代理 | `http://127.0.0.1:9910` |
| `DEFAULT_LOCALE` | 默认语言 | `en` |
| `SIGNAL_DATA_MAX_AGE` | 信号数据最大允许时长（秒，超限不触发） | `600` |
| `COOLDOWN_SECONDS` | signal-service PG 全局冷却时间（秒，持久化） | `300` |
| `SIGNAL_DATA_MAX_AGE` | 信号数据最大允许时长（秒，超限不触发） | `600` |
| `COOLDOWN_SECONDS` | signal-service PG 全局冷却时间（秒，持久化） | `300` |

### 10.2 币种管理

| 变量 | 说明 |
|:---|:---|
| `SYMBOLS_GROUPS` | 使用的分组（main4/main6/main20/auto/all） |
| `SYMBOLS_GROUP_<name>` | 自定义分组定义（如 `SYMBOLS_GROUP_defi`） |
| `SYMBOLS_EXTRA` | 额外添加的币种 |
| `SYMBOLS_EXCLUDE` | 强制排除的币种 |

### 10.3 数据采集配置

| 变量 | 服务 | 说明 |
|:---|:---|:---|
| `BACKFILL_MODE` | data-service | 回填模式（all/days/none） |
| `BACKFILL_DAYS` | data-service | 回填天数（BACKFILL_MODE=days 时生效） |
| `BACKFILL_START_DATE` | data-service | 回填起始日期（可选） |
| `MAX_CONCURRENT` | data-service | 最大并发请求数（默认 5） |
| `RATE_LIMIT_PER_MINUTE` | data-service | 每分钟最大请求数（默认 1800） |
| `INTERVALS` | data-service | K线周期（逗号分隔） |
| `KLINE_INTERVALS` | data-service | WebSocket 订阅周期 |
| `FUTURES_INTERVALS` | data-service | 期货指标周期（最小 5m） |

### 10.4 服务配置

| 变量 | 服务 | 说明 |
|:---|:---|:---|
| `MAX_WORKERS` | trading-service | 计算线程数 |
| `COMPUTE_BACKEND` | trading-service | 计算后端（thread/process/hybrid） |
| `HIGH_PRIORITY_TOP_N` | trading-service | auto 模式高优先级币种数量 |
| `VIS_SERVICE_PORT` | vis-service | 监听端口（默认 8087） |
| `FATE_BOT_TOKEN` | fate-service | 命理 Bot Token |
| `FATE_SERVICE_PORT` | fate-service | API 端口（默认 8001） |
| `MARKETS_SERVICE_DATABASE_URL` | markets-service | 独立数据库连接 |
| `CRYPTO_WRITE_MODE` | markets-service | 写入模式（raw/legacy） |
| `ORDER_BOOK_TICK_INTERVAL` | markets-service | L1 tick 采样间隔（秒，默认 1） |
| `ORDER_BOOK_FULL_INTERVAL` | markets-service | L2 full 采样间隔（秒，默认 5） |
| `ORDER_BOOK_DEPTH` | markets-service | 每侧档位数（默认 1000） |
| `ORDER_BOOK_RETENTION_DAYS` | markets-service | 数据保留天数（默认 30） |

### 10.5 外部地址配置

| 变量 | 说明 |
|:---|:---|
| `BINANCE_WEB_BASE` | Telegram 卡片/快照中的 Binance 页面跳转前缀 |
| `BINANCE_PING_URL` | 网络连通性探测地址（check_env/start 脚本使用） |
| `SYMBOLS_ALL_URL` | 全市场币种清单地址（symbols 模块使用） |
| `TELEGRAM_API_BASE` | Telegram API 基址（脚本与 Node 服务统一） |
| `POLYMARKET_WEB_BASE` | Polymarket 页面链接前缀（Node 信号格式化） |
| `KALSHI_WEB_BASE` | Kalshi 页面链接前缀（Node 信号格式化） |
| `OPINION_WEB_BASE` | Opinion 页面链接前缀（Node 信号格式化） |
| `NODEJS_SETUP_URL` | 远程部署脚本 Node.js 安装源地址 |
| `NOFX_MARKET_API_BASE_URL_DEFAULT` | nofx-dev 默认行情 API 基址（tradecat 模式） |
| `NOFX_DATA_API_BASE` | nofx-dev 默认策略数据 API 基址（AI500/OI/Quant） |
| `NOFX_BYBIT_BASE_URL` / `NOFX_BITGET_BASE_URL` / `NOFX_OKX_BASE_URL` | nofx-dev 交易所 API 基址覆盖 |
| `NOFX_LIGHTER_MAINNET_BASE_URL` / `NOFX_LIGHTER_TESTNET_BASE_URL` / `NOFX_ASTER_BASE_URL` | nofx-dev DEX API 基址覆盖 |

---

## 11. 快速参考卡片

```bash
# 初始化
./scripts/init.sh

# 启动/停止
./scripts/start.sh start|stop|status

# 单服务管理
cd services/<layer>/<name> && make start|stop|status

# 代码检查
cd services/<layer>/<name> && make lint format test

# 验证
./scripts/verify.sh

# 数据库（LF=5433，HF=15432）
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data
sqlite3 libs/database/services/telegram-service/market_data.db

# 备份
./scripts/export_timescaledb.sh
```

---

## 12. 变更日志

- 2026-01-28: 新增信号相关性分析脚本与文档，输出分析产物目录。
- 2026-01-29: 新增宣传材料与比赛汇报材料文档。
- 2026-01-29: Tradecat Preview API 新增 `/api/futures/base-data`（直读 SQLite 基础数据）。
- 2026-02-01: 修复 data-service K线 REST 补齐在部分返回为字符串时间戳时的崩溃；新增 trading-service 类比预测脚本（15m 全历史检索相似窗口并输出未来分布）。
- 2026-02-01: 新增 trading-service K线质量报告脚本（全历史缺口与近30天日条数校验），用于启动预测前的“是否齐全”自检。
- 2026-02-10: 硬编码地址治理：Binance/Telegram/Polymarket/Kalshi/Opinion/NOFX URL 统一迁移到环境变量，脚本与服务共享配置入口。
- 2026-02-10: 新增 `docs/analysis/layer_contract_one_pager.md`，定义采集/处理/消费三层的输入输出、幂等键、时间语义、重试策略与观测指标。
- 2026-02-10: 新增 `docs/analysis/repo_structure_design.md`，给出三层单向数据流的理想目录结构与现实渐进迁移方案。
- 2026-02-10: 新增 `docs/architecture/CONSTITUTION.md`，确立长期治理的系统宪法（单向依赖/单一真相源/幂等与时间语义/可观测/变更可回滚）与强制约束清单。
- 2026-02-14: 归档 `services/ingestion/data-service` → `artifacts/services-archived/ingestion/data-service`，避免污染现行采集链路。
- 2026-02-12: 新增综合市场数据库 DDL（`core/storage/crypto`），并把 Binance Vision 的“基元物理层 vs 可派生层”按脚本/表集合分层（均在 `crypto` 根内；表名使用 `raw_*`/`agg_*` 前缀；`raw_option_eoh_summary` 按约束保留在物理层）。
- 2026-02-15: 新增 `docs/analysis/INDEX.md` 与 `docs/analysis/crypto_raw_trades_hardening_runbook.md`，并把入口写入 `AGENTS.md` 与采集服务契约文档。
- 2026-02-16: 恢复 `services/ingestion/data-service/`（低频/分时兼容链路），并同步更新文档/脚本中的历史路径引用。
