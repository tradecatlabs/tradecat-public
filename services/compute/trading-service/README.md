# Trading Service

指标计算服务：从 TimescaleDB 读取 K线/期货数据，计算 38 个技术指标，默认写入 SQLite（`market_data.db`），也支持写入 PG（`tg_cards.*`）或双写（灰度切换/回滚）。

## 功能

| 功能 | 说明 |
|:---|:---|
| **38 个技术指标** | MACD、KDJ、RSI、布林带、K线形态、期货情绪等 |
| **高优先级识别** | 自动识别 130+ 活跃币种优先计算 |
| **多周期支持** | K线 1m/5m/15m/1h/4h/1d/1w |
| **并行计算** | 多线程计算，< 3分钟完成全量 |

## 目录结构

```
src/
├── core/                    # 计算引擎
│   ├── engine.py            # 同步计算引擎
│   ├── async_full_engine.py # 异步计算引擎
│   └── event_engine.py      # 事件驱动引擎
├── db/
│   ├── reader.py            # TimescaleDB 读取
│   └── cache.py             # 数据缓存
├── indicators/
│   ├── base.py              # 指标基类 + 注册表
│   ├── incremental/         # 增量指标
│   └── batch/               # 批量指标 (38个)
│       ├── k_pattern.py     # K线形态检测
│       ├── bollinger.py     # 布林带
│       └── ...
├── observability/           # 可观测性
├── config.py                # 配置
├── simple_scheduler.py      # 轮询调度器
└── __main__.py              # CLI 入口
```

## 快速开始

### 环境要求

- Python >= 3.10
- TimescaleDB (端口 5433)
- TA-Lib (系统库)

### 安装

```bash
# 方式一：使用初始化脚本
cd /path/to/tradecat
./scripts/init.sh trading-service

# 方式二：手动安装
cd services/compute/trading-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 安装形态检测库
pip install m-patternpy
pip install tradingpattern --no-deps
```

### 配置

```bash
cp config/.env.example config/.env
vim config/.env
```

### 启动

```bash
# 启动轮询模式（推荐）
./scripts/start.sh start

# 查看状态
./scripts/start.sh status

# 停止
./scripts/start.sh stop

# 一次性计算
python3 -m src --once

# 指定参数
python3 -m src --once --symbols BTCUSDT,ETHUSDT --intervals 5m,15m
```

## 配置说明

### 环境变量 (config/.env)

| 变量 | 默认值 | 说明 |
|:---|:---|:---|
| `DATABASE_URL` | - | TimescaleDB 连接串 |
| `INDICATOR_SQLITE_PATH` | - | SQLite 输出路径 |
| `INDICATOR_STORE_MODE` | sqlite | 指标存储后端：`sqlite|pg|dual` |
| `INDICATOR_PG_SCHEMA` | tg_cards | PG 指标 schema（`mode=pg|dual` 生效） |
| `MAX_WORKERS` | 4 | 并行线程数 |
| `COMPUTE_BACKEND` | thread | 计算后端 |

### .env.example

```bash
DATABASE_URL=postgresql://user:password@localhost:5432/market_data
INDICATOR_SQLITE_PATH=/path/to/tradecat/assets/database/services/telegram-service/market_data.db
INDICATOR_STORE_MODE=sqlite
INDICATOR_PG_SCHEMA=tg_cards
MAX_WORKERS=4
COMPUTE_BACKEND=thread
```

## 指标列表 (38个)

### 趋势指标
- EMA、MACD、SuperTrend、ADX、Ichimoku、Donchian、Keltner、趋势线

### 动量指标
- RSI、KDJ、CCI、WilliamsR、MFI、RSI谐波

### 波动指标
- 布林带、ATR、ATR波幅、支撑阻力

### 成交量指标
- OBV、CVD、VWAP、成交量比率、流动性、VPVR

### K线形态
- 61种蜡烛形态 (TA-Lib)
- 价格形态：头肩、双顶、三角形、楔形、通道 (patternpy)

### 期货指标
- 持仓量、多空比、主动买卖比、期货情绪聚合

## 数据流

```
TimescaleDB (candles_1m)
        │
        ▼
    DataReader (批量读取)
        │
        ▼
    Engine (并行计算 38 指标)
        │
        ▼
    Indicator Store
      ├─ SQLite (market_data.db, 38张表)   [mode=sqlite|dual]
      └─ PG (tg_cards.*, 38张表)           [mode=pg|dual]
        │
        ▼
    telegram-service (读取展示)
```

## 输出

写入位置取决于 `INDICATOR_STORE_MODE`：

- `sqlite|dual`：写入 `assets/database/services/telegram-service/market_data.db`
- `pg|dual`：写入 `DATABASE_URL` 指向的 PG 库的 `tg_cards.*`（可用 `INDICATOR_PG_SCHEMA` 覆盖）

初始化 `tg_cards` DDL（仅需一次）：

```bash
PGPASSWORD=postgres psql 'postgresql://postgres:postgres@localhost:5433/market_data' \
  -f assets/database/db/schema/021_tg_cards_sqlite_parity.sql
```

SQLite 表名示例：

| 表名示例 | 说明 |
|:---|:---|
| `基础数据同步器.py` | 价格、成交量、成交额 |
| `K线形态扫描器.py` | 形态类型、检测数量、强度 |
| `期货情绪聚合表.py` | 持仓、多空比、情绪分 |

## 日志

```bash
tail -f logs/simple_scheduler.log
```

## 常见问题

### TA-Lib 安装失败

```bash
# 先安装系统库
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib && ./configure --prefix=/usr && make && sudo make install
cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# 再安装 Python 包
pip install TA-Lib
```

### K线形态显示"无形态"

```bash
# 安装形态检测库
pip install m-patternpy
pip install tradingpattern --no-deps  # 忽略 numpy 版本冲突

# 重启服务
./scripts/start.sh restart
```

### 计算耗时过长

```bash
# 检查高优先级币种数量
grep "高优先级" logs/simple_scheduler.log

# 减少并发
MAX_WORKERS=2 ./scripts/start.sh start
```
