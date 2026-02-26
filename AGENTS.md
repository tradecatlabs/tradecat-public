# TradeCat - AI Agent 操作手册（Operating Manual）

本文件面向自动化/AI 编码 Agent：**给出可执行路径 + 明确边界约束**，避免“瞎改/大改/改出事故”。

---

## 1) Mission & Scope（目标与边界）

### 允许

- 修改服务代码：`services/**/src/`
- 修改服务脚本：`services/*/scripts/` 与 `scripts/`
- 更新文档：`README.md`、`README_EN.md`、`AGENTS.md`、`assets/docs/**`（保留 `docs -> assets/docs` 兼容 symlink）
- 更新配置模板：`config/.env.example`

### 禁止

- 禁止修改生产配置：`config/.env`（包含密钥/凭证）
- 禁止删除或改写数据库文件：`assets/database/**`（`libs/` 为兼容 symlink；除非任务明确要求）
- 禁止大范围重构（无明确任务授权）
- 禁止引入未经验证的第三方依赖（新增依赖必须同时更新锁文件/说明）

### 敏感区域（只读/慎动）

| 路径 | 说明 |
|:---|:---|
| `config/.env` | 运行时私密配置（不提交） |
| `assets/database/services/**` | SQLite 持久化与审计数据（`libs/` 为兼容 symlink） |
| `backups/` | 导出/备份产物 |

---

## 2) Golden Path（推荐执行路径）

```bash
# 0) 环境检查（推荐）
./scripts/check_env.sh

# 1) 初始化（创建各服务 .venv + 安装依赖）
./scripts/init.sh

# 2) 准备配置（模板 → 运行时）
cp config/.env.example config/.env && chmod 600 config/.env
vim config/.env

# 3) 启动核心服务
./scripts/start.sh start
./scripts/start.sh status

# 4) 修改代码后验证
./scripts/verify.sh
```

---

## 3) Must-Run Commands（必须执行/常用）

### 顶层脚本（来源：`scripts/`）

- 初始化：`./scripts/init.sh`
- 启动/停止/状态：`./scripts/start.sh start|stop|status|restart`
- 守护模式：`./scripts/start.sh daemon|daemon-stop`
- 校验：`./scripts/verify.sh`

### 单服务（来源：各服务 `Makefile`）

```bash
cd services/<layer>/<service-name>
make install
make lint
make format
make test
make start|stop|status
```

---

## 4) Code Change Rules（修改约束）

### 架构分层（单向依赖）

```text
ingestion  -> TimescaleDB (LF/HF) -> compute -> SQLite -> consumption
```

- ingestion：写 TimescaleDB（事实/原始数据）
- compute：读 TimescaleDB，计算指标，写 SQLite（展示用）
- consumption：读 SQLite/导出卡片/写 Sheets/API/Telegram

### 服务边界（来自仓库结构 `services/`）

- `services/ingestion/*`：采集层（写 TimescaleDB）
- `services/compute/*`：计算层（指标/信号/AI）
- `services/consumption/*`：消费层（Telegram/API/Sheets）

### 兼容性要求（以仓库为准）

- 推荐 Python：**3.12+**
  - 证据：CI 使用 Python 3.12（`.github/workflows/ci.yml`）
  - 证据：各服务 `services/*/*/pyproject.toml` 声明 `requires-python = ">=3.12"`
- 脚本最低门槛：`scripts/init.sh` 检查 Python >= 3.10（不代表所有服务在 3.10 下可用）
- 数据库端口（模板默认，来源：`config/.env.example`）：
  - LF：`DATABASE_URL` 默认 `localhost:5433/market_data`
  - HF（可选）：`BINANCE_VISION_DATABASE_URL` 默认 `localhost:15432/market_data`

### 依赖添加规则

1) 先确认仓库/服务内是否已存在相同依赖  
2) 只在对应服务的 `requirements*.txt` 或 `pyproject.toml` 增加  
3) 如仓库要求锁定：同步更新 `requirements.lock.txt`（服务内已有）  
4) 文档同步：`config/.env.example` / README / AGENTS 需要同步说明

---

## 5) Style & Quality（质量标准）

- Python 格式化/静态检查：ruff（服务内 `pyproject.toml` 配置）
- 行长：120（服务内 ruff 配置）
- 日志：使用 `logging`，异常必须 `exc_info=True`（避免吞栈）

---

## 6) Project Map（结构速览）

```text
tradecat/
├── config -> assets/config
├── scripts/
│   ├── init.sh
│   ├── start.sh
│   ├── check_env.sh
│   └── verify.sh
├── services/
│   ├── ingestion/
│   │   ├── data-service/
│   │   └── binance-vision-service/
│   ├── compute/
│   │   ├── trading-service/
│   │   ├── signal-service/
│   │   └── ai-service/
│   └── consumption/
│       ├── telegram-service/
│       ├── api-service/
│       └── sheets-service/
├── assets/
│   ├── docs/
│   ├── tasks/
│   └── artifacts/
└── libs -> assets
```

---

## 7) Common Pitfalls（常见坑与修复）

### `.env` 权限导致服务启动失败

```bash
chmod 600 config/.env
```

### TimescaleDB 端口不一致

- 证据：`config/.env.example` 默认 LF=5433、HF=15432
- 修复：统一 `config/.env` 中的端口，并同步所有脚本/示例命令

### TA-Lib 安装失败（形态指标需要）

```bash
sudo apt-get update
sudo apt-get install -y build-essential

wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib && ./configure --prefix=/usr && make && sudo make install
cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

pip install TA-Lib
```

### sheets-service 在代理环境下偶发 SSL 抖动

现象（常见日志）：`SSLError: DECRYPTION_FAILED_OR_BAD_RECORD_MAC`

- 若使用 SA 写入：可设置 `SHEETS_SA_NET_WRITE_RETRIES` 提升幂等写入的重试容忍度  
  - 证据：`services/consumption/sheets-service/src/sa_sheets_writer.py` 读取该环境变量

---

## 8) PR / Commit Rules（提交与 CI）

- Commit message 推荐：

```text
<type>(<scope>): <subject>
```

`type`: `feat|fix|docs|refactor|chore|style`

- CI（证据：`.github/workflows/ci.yml`）：
  - ruff check（仅针对 `services/`）
  - py_compile 抽样（前 50 个 `.py`）

---

## 9) Documentation Sync Rule（强制同步规则）

当你修改了以下任一项，必须同步更新文档：

- 新增/修改命令：更新 `README.md` / `AGENTS.md`
- 新增/修改配置项：更新 `config/.env.example`，并在 `README.md` / `AGENTS.md` 说明
- 目录结构/服务职责变更：更新 `README.md` / `AGENTS.md`

不确定项必须写 `TODO` 并标注需要核对的文件路径/字段名，禁止猜测。
