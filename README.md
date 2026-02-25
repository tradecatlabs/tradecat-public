# TradeCat（交易猫）

TradeCat 是一个以 **TimescaleDB + 多服务流水线** 为核心的量化数据/指标/信号/展示系统：采集 → 存储 → 计算 → Telegram/Sheets/API 消费层。

本仓库以脚本化方式组织服务，适合本地开发、WSL2、以及服务器部署。

---

## 功能特性

- 多服务分层：`ingestion → compute → consumption`
- TimescaleDB：K 线/指标时序数据（LF）与原子事实（HF，可选）分离
- 指标计算：`trading-service` 写入 SQLite（供 Telegram/Sheets/API 展示层读取）
- Telegram Bot：排行榜卡片、币种查询、信号展示
- Google Sheets（可选）：公开只读看板 + 自动写入（SA/Webhook）
- REST API（可选）：只读查询接口

---

## 快速开始（最短可跑通）

### 环境要求

- Python：推荐 **3.12+**（CI 使用 3.12；各服务 `services/*/*/pyproject.toml` 声明 `requires-python >=3.12`）
- PostgreSQL + TimescaleDB：用于 `DATABASE_URL`（LF）与可选的 `BINANCE_VISION_DATABASE_URL`（HF）
- 可选：`psql`（便于排障/查询）、TA-Lib（K 线形态相关）

> 注意：`scripts/init.sh` 的最低 Python 检查为 3.10，但这不保证所有服务依赖在 3.10 下可用。

### 1) 环境检查（推荐）

```bash
./scripts/check_env.sh
```

### 2) 初始化（创建 .venv + 安装依赖）

```bash
./scripts/init.sh
```

### 3) 配置（必须）

```bash
cp config/.env.example config/.env && chmod 600 config/.env
vim config/.env
```

关键配置项（来源：`config/.env.example`）：

- Telegram：`BOT_TOKEN`
- 数据库：
  - LF：`DATABASE_URL`（默认 `localhost:5433/market_data`）
  - HF（可选）：`BINANCE_VISION_DATABASE_URL`（默认 `localhost:15432/market_data`）
- 代理（按需）：`HTTP_PROXY` / `HTTPS_PROXY`
- Google Sheets（可选）：`SHEETS_*`（见 `config/.env.example` 的 “Google Sheets 公共看板” 段落）

### 4) 启动核心服务

```bash
./scripts/start.sh start
./scripts/start.sh status
```

`./scripts/start.sh` 默认管理的核心服务为：

- `ai-service`（就绪检查/子模块，非独立常驻进程）
- `signal-service`
- `telegram-service`
- `trading-service`

可选服务（需手动启动）：

```bash
cd services/consumption/api-service && ./scripts/start.sh start   # 默认端口 8088（可用 API_SERVICE_PORT 覆盖）
cd services/consumption/sheets-service && ./scripts/start.sh start
```

---

## 目录结构（与仓库一致）

```text
tradecat/
├── config/                  # 全局配置：config/.env.example → config/.env（不提交）
├── scripts/                 # 顶层脚本：init/start/verify/check_env/导出等
├── services/                # 分层服务：ingestion/compute/consumption
│   ├── ingestion/
│   ├── compute/
│   └── consumption/
├── libs/database/           # SQLite/DDL/CSV 等（敏感数据禁止随意改动）
├── docs/                    # 文档（分析/架构/运维）
├── logs/                    # 顶层日志（daemon）
└── run/                     # 顶层 PID（daemon）
```

---

## 常用命令

### 全局

```bash
./scripts/init.sh
./scripts/start.sh start|stop|status|restart
./scripts/start.sh daemon|daemon-stop
./scripts/verify.sh
```

### 单服务（统一 Makefile 接口）

```bash
cd services/<layer>/<service-name>
make install
make lint
make format
make test
make start|stop|status
```

---

## 配置说明（重要约束）

### config/.env 权限

启动脚本会校验权限；建议：

```bash
chmod 600 config/.env
```

### TimescaleDB 端口约定（按模板默认）

- LF：5433（`DATABASE_URL` / `DATA_SERVICE_DATABASE_URL`）
- HF：15432（`BINANCE_VISION_DATABASE_URL`）

若你自行改动端口，需 **全局统一**（配置 + 脚本 + 示例命令）。

---

## Troubleshooting / FAQ

- 数据库未就绪：`./scripts/start.sh start` 会调用 `pg_isready` 做就绪检查；先确认 `DATABASE_URL` 指向的 PG 已启动。
- `.env` 权限不安全：执行 `chmod 600 config/.env`。
- TA-Lib 安装失败：见 `AGENTS.md` 的 “Common Pitfalls”。
- Sheets 写入偶发 SSL 抖动（代理环境常见）：可在 `sheets-service` 配置 `SHEETS_SA_NET_WRITE_RETRIES`（代码支持，默认 2；详见 `AGENTS.md`）。

---

## 贡献与 CI

- CI：`.github/workflows/ci.yml`（ruff + py_compile 抽样，不跑完整 tests）
- 建议提交前运行：`./scripts/verify.sh`
- Commit message 建议：`feat|fix|docs|refactor|chore(scope): subject`

---

## 免责声明（简版）

本项目仅用于技术研究与社区协作，不构成任何投资建议；数字资产波动巨大，请自行评估风险并独立决策。
