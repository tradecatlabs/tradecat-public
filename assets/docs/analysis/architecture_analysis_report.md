# TradeCat 项目整体架构分析报告

> 生成时间: 2026-01-29  
> 分析范围: 14个微服务、核心数据流、存储架构

---

## 1. 系统概览

TradeCat 是一个加密货币数据分析与交易辅助平台，采用微服务架构，核心功能包括：
- 多市场数据采集（加密货币、美股、A股、宏观经济）
- 34个技术指标计算
- 129条信号检测规则
- Telegram Bot 交互界面
- AI 智能分析（Wyckoff 方法论）

### 1.1 技术栈

| 层级 | 技术选型 |
|:---|:---|
| 语言 | Python 3.12, Node.js, Go |
| 数据库 | TimescaleDB (PostgreSQL 16), SQLite |
| 消息/事件 | SignalPublisher (内存事件总线) |
| API | FastAPI, python-telegram-bot |
| 数据处理 | pandas, numpy, TA-Lib |
| 外部数据 | CCXT, Cryptofeed, AKShare, yfinance |

---

## 2. 核心业务流程图

### 2.1 主数据流架构

```mermaid
graph TD
    subgraph 外部数据源["🌐 外部数据源"]
        BINANCE_WS["Binance WebSocket<br>实时K线"]
        BINANCE_REST["Binance REST API<br>期货指标"]
        YFINANCE["yfinance<br>美股数据"]
        AKSHARE["AKShare<br>A股数据"]
    end

    subgraph 数据采集层["📦 数据采集层"]
        DS["data-service<br>加密货币采集"]
        MS["markets-service<br>全市场采集"]
        DC["datacat-service<br>新一代采集框架"]
    end

    subgraph 持久化层["🗄️ 持久化层"]
        TSDB[("TimescaleDB :5434<br>candles_1m (3.73亿条)<br>futures_metrics_5m")]
        SQLITE[("SQLite<br>market_data.db<br>指标结果")]
        COOLDOWN_DB[("SQLite<br>cooldown.db<br>信号冷却")]
        HISTORY_DB[("SQLite<br>signal_history.db<br>信号历史")]
    end

    subgraph 计算层["📊 计算层"]
        TS["trading-service<br>34个指标模块"]
        TS_ENGINE["Engine<br>IO→Compute→Storage"]
    end

    subgraph 信号层["🔔 信号层"]
        SIG["signal-service<br>129条规则"]
        SIG_SQLITE["SQLite Engine"]
        SIG_PG["PG Engine"]
        SIG_PUB["SignalPublisher<br>事件发布"]
    end

    subgraph 用户交互层["👤 用户交互层"]
        TG["telegram-service<br>Bot交互"]
        TG_CARDS["Cards (20+)<br>排行榜"]
        TG_ADAPTER["Signals Adapter<br>信号适配"]
        AI["ai-service<br>Wyckoff分析"]
        API["api-service<br>REST API :8000"]
        VIS["vis-service<br>可视化 :8087"]
    end

    %% 数据采集流
    BINANCE_WS --> DS
    BINANCE_REST --> DS
    YFINANCE --> MS
    AKSHARE --> MS
    BINANCE_WS --> DC
    BINANCE_REST --> DC

    %% 写入数据库
    DS --> TSDB
    MS --> TSDB
    DC --> TSDB

    %% 指标计算流
    TSDB --> TS
    TS --> TS_ENGINE
    TS_ENGINE --> SQLITE

    %% 信号检测流
    SQLITE --> SIG_SQLITE
    TSDB --> SIG_PG
    SIG_SQLITE --> SIG
    SIG_PG --> SIG
    SIG --> SIG_PUB
    SIG_PUB --> COOLDOWN_DB
    SIG_PUB --> HISTORY_DB

    %% 用户服务
    SQLITE --> TG_CARDS
    TG_CARDS --> TG
    SIG_PUB --> TG_ADAPTER
    TG_ADAPTER --> TG
    TSDB --> AI
    AI --> TG
    SQLITE --> API
    TSDB --> API
    SQLITE --> VIS

    style TSDB fill:#4169E1,color:#fff
    style SQLITE fill:#2E8B57,color:#fff
    style SIG_PUB fill:#FF6347,color:#fff
```

### 2.2 指标计算流程（trading-service 内部）

```mermaid
graph LR
    subgraph IO层["IO 层 (只读)"]
        LOAD["load_klines()<br>加载K线"]
        CACHE["preload_futures_cache()<br>期货缓存"]
    end

    subgraph Compute层["Compute 层 (纯计算)"]
        COMPUTE["compute_all()<br>多进程并行"]
        IND["34个指标模块<br>batch/incremental"]
    end

    subgraph Storage层["Storage 层 (只写)"]
        WRITE["write_results()<br>批量写入"]
        POST["update_market_share()<br>后处理"]
    end

    LOAD --> COMPUTE
    CACHE --> COMPUTE
    COMPUTE --> IND
    IND --> WRITE
    WRITE --> POST
```

### 2.3 信号检测流程（signal-service 内部）

```mermaid
graph TD
    subgraph 数据源["数据源"]
        SQLITE_SRC["SQLite<br>market_data.db"]
        PG_SRC["PostgreSQL<br>TimescaleDB"]
    end

    subgraph 引擎["检测引擎"]
        SQLITE_ENG["SQLite Engine<br>指标规则"]
        PG_ENG["PG Engine<br>K线/期货规则"]
    end

    subgraph 规则["129条规则 (8分类)"]
        CORE["core"]
        MOMENTUM["momentum"]
        TREND["trend"]
        VOLATILITY["volatility"]
        VOLUME["volume"]
        FUTURES["futures"]
        PATTERN["pattern"]
        MISC["misc"]
    end

    subgraph 输出["输出"]
        PUBLISHER["SignalPublisher"]
        COOLDOWN["冷却持久化"]
        HISTORY["历史记录"]
        TELEGRAM["Telegram 推送"]
    end

    SQLITE_SRC --> SQLITE_ENG
    PG_SRC --> PG_ENG
    SQLITE_ENG --> CORE
    SQLITE_ENG --> MOMENTUM
    SQLITE_ENG --> TREND
    PG_ENG --> VOLATILITY
    PG_ENG --> VOLUME
    PG_ENG --> FUTURES
    PG_ENG --> PATTERN
    PG_ENG --> MISC

    CORE --> PUBLISHER
    MOMENTUM --> PUBLISHER
    TREND --> PUBLISHER
    VOLATILITY --> PUBLISHER
    VOLUME --> PUBLISHER
    FUTURES --> PUBLISHER
    PATTERN --> PUBLISHER
    MISC --> PUBLISHER

    PUBLISHER --> COOLDOWN
    PUBLISHER --> HISTORY
    PUBLISHER --> TELEGRAM
```

---

## 3. 服务清单与职责边界

### 3.1 分层服务 (services/{ingestion,compute,consumption}/)

| 层 | 服务 | 位置 | 入口 | 职责 | 数据依赖 | 数据输出 |
|:---|:---|:---|:---|:---|:---|:---|
| ingestion | **binance-vision-service** | `services/ingestion/binance-vision-service` | `src/__main__.py` | Binance Vision Raw 对齐采集（ccxtpro WS/REST + Vision ZIP 回填） | Binance API / Binance Vision | TimescaleDB |
| compute | **trading-service** | `services/compute/trading-service` | `src/__main__.py` | 技术指标计算 | TimescaleDB | SQLite market_data.db |
| compute | **signal-service** | `services/compute/signal-service` | `src/__main__.py` | 信号规则检测 | SQLite、TimescaleDB | SignalPublisher |
| compute | **ai-service** | `services/compute/ai-service` | `src/__main__.py` | AI 分析（telegram 子模块） | TimescaleDB、SQLite | Telegram |
| consumption | **telegram-service** | `services/consumption/telegram-service` | `src/__main__.py` | Bot交互、排行榜展示、信号推送UI | SQLite、SignalPublisher | Telegram |
| consumption | **api-service** | `services/consumption/api-service` | `src/__main__.py` | REST API（CoinGlass V4 风格） | TimescaleDB、SQLite | HTTP |

> 注：`services/ingestion/data-service/` 为低频/分时兼容链路（1m K线、5m 指标），默认不进入顶层启动/校验链路，需要时手动运行。

> 说明：历史 `services-preview/*` 概念已从本仓库目录移除；如需预览服务，请在独立仓库/分支维护。

---

## 4. 数据存储架构

### 4.1 TimescaleDB (端口 5433/5434)

| 表名 | 数据量 | 说明 |
|:---|:---|:---|
| `market_data.candles_1m` | 3.73亿条 (99GB) | 1分钟K线 |
| `market_data.binance_futures_metrics_5m` | 9457万条 (5GB) | 期货指标 |
| `market_data.*_last` | 物化视图 | 各周期最新数据 |

**端口说明**:
- 5433: 旧库（单schema，与早期脚本兼容）
- 5434: 新库（raw/agg/quality 多schema，.env.example 默认）

### 4.2 SQLite 数据库

| 路径 | 用途 | 写入者 | 读取者 |
|:---|:---|:---|:---|
| `assets/database/services/telegram-service/market_data.db` | 指标结果 | trading-service | telegram/ai/signal/api/vis |
| `assets/database/services/signal-service/cooldown.db` | 信号冷却状态 | signal-service | signal-service |
| `assets/database/services/signal-service/signal_history.db` | 信号触发历史 | signal-service | 分析脚本 |

---

## 5. 模块边界约束

根据 AGENTS.md 定义的边界规则：

| 服务 | 允许 | 禁止 |
|:---|:---|:---|
| data-service | 数据采集、存储到 TimescaleDB | 计算指标 |
| trading-service | 指标计算、写入 SQLite | 直接推送消息 |
| telegram-service | Bot交互、信号推送 UI | 包含信号检测逻辑 |
| signal-service | 信号检测、规则引擎 | Telegram依赖、写入业务数据库 |
| api-service | REST API数据查询 | 写入数据库 |
| vis-service | 可视化渲染 | 写入数据库 |

---

## 6. 关键技术决策

### 6.1 计算引擎分层 (trading-service)

采用 IO/Compute/Storage 三层分离架构：
- **IO层**: 只读，负责从 TimescaleDB 加载K线数据
- **Compute层**: 纯计算，多进程并行，不做数据库读写
- **Storage层**: 只写，批量写入 SQLite

### 6.2 信号检测双引擎 (signal-service)

- **SQLite Engine**: 读取指标结果表，适用于基于指标的规则
- **PG Engine**: 直接读取 TimescaleDB，适用于K线/期货原始数据规则

### 6.3 事件驱动通信

- 使用 `SignalPublisher` 内存事件总线
- 支持多订阅者（Telegram推送、历史持久化）
- 冷却机制防止重复推送

---

## 7. 附录

### 7.1 服务启动命令

```bash
# 核心服务一键启动
./scripts/start.sh start

# 单服务管理
cd services/<layer>/<name> && make start|stop|status

# 守护进程模式
./scripts/start.sh daemon
```

### 7.2 数据流验证命令

```bash
# 检查 TimescaleDB
PGPASSWORD=postgres psql -h localhost -p 5434 -U postgres -d market_data \
  -c "SELECT COUNT(*) FROM market_data.candles_1m"

# 检查 SQLite
sqlite3 assets/database/services/telegram-service/market_data.db ".tables"
```
