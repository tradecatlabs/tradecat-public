# Data Service

> ⚠️ **兼容链路（非默认启动）**：本服务用于低频/分时数据（1m K线、5m 指标）采集与历史补齐。  
> 高频/HFT 原子事实（trades/bookTicker/bookDepth 等）请优先使用：`services/ingestion/binance-vision-service`。

Binance 期货市场数据采集服务，提供 1m K线和 5m 期货指标的实时采集与历史补齐。

## 功能

| 功能 | 说明 |
|:---|:---|
| **WebSocket K线采集** | 订阅 615+ USDT 永续合约 1m K线，3秒窗口批量写入 |
| **期货指标采集** | 5分钟周期采集持仓量、多空比、主动买卖比 |
| **数据补齐** | ZIP 历史下载 + REST API 分页补齐 + 缺口巡检 |
| **限流保护** | 全局限流器，自动检测 IP Ban 并等待 |

## 目录结构

```
src/
├── adapters/           # 外部服务适配层
│   ├── ccxt.py         # 交易所 API
│   ├── cryptofeed.py   # WebSocket 适配器
│   ├── timescale.py    # TimescaleDB 适配器
│   ├── rate_limiter.py # 限流器
│   └── metrics.py      # 监控指标
├── collectors/         # 数据采集器
│   ├── ws.py           # WebSocket K线采集
│   ├── metrics.py      # 期货指标采集
│   ├── backfill.py     # 数据补齐
│   ├── alpha.py        # Alpha 代币列表
│   └── downloader.py   # 文件下载器
├── config.py           # 配置管理
└── __main__.py         # 入口
```

## 快速开始

### 环境要求

- Python >= 3.10
- TimescaleDB（以 `DATABASE_URL` 为准；旧链路常见端口 5433）
- 代理服务（访问 Binance）

### 安装

```bash
cd services/ingestion/data-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 配置

```bash
cp assets/config/.env.example assets/config/.env
vim assets/config/.env
```

### 启动

```bash
# 进入服务目录后启动（本服务自身的守护脚本）
cd services/ingestion/data-service
./scripts/start.sh start
./scripts/start.sh status
./scripts/start.sh stop

# 单独启动组件
PYTHONPATH=src python3 -m collectors.ws        # WebSocket
PYTHONPATH=src python3 -m collectors.metrics   # Metrics
PYTHONPATH=src python3 -m collectors.backfill --all  # 补齐
```

## 配置说明

### 环境变量 (assets/config/.env)

| 变量 | 默认值 | 说明 |
|:---|:---|:---|
| `DATABASE_URL` | - | TimescaleDB 连接串 |
| `DATA_SERVICE_DATABASE_URL` | - | data-service 专用 TimescaleDB（优先于 `DATABASE_URL`，用于两库共存） |
| `HTTP_PROXY` | - | HTTP 代理地址 |
| `RATE_LIMIT_PER_MINUTE` | 1800 | API 限流 |
| `MAX_CONCURRENT` | 5 | 最大并发数 |
| `BINANCE_WS_GAP_INTERVAL` | 600 | 缺口巡检间隔（秒） |
| `BINANCE_WS_SOURCE` | binance_ws | 数据来源标识 |

### .env.example

```bash
DATABASE_URL=postgresql://user:password@localhost:5432/market_data
# 两库共存时可选：data-service 专用库（优先于 DATABASE_URL）
DATA_SERVICE_DATABASE_URL=postgresql://user:password@localhost:5433/market_data
HTTP_PROXY=http://127.0.0.1:7890
RATE_LIMIT_PER_MINUTE=1800
MAX_CONCURRENT=5
```

## 数据表

| 表名 | 说明 | 数据量 |
|:---|:---|:---|
| `market_data.candles_1m` | 1分钟 K线 | 3.73亿条 |
| `market_data.binance_futures_metrics_5m` | 5分钟期货指标 | 9457万条 |

## 数据流

```
Binance
   │
   ├── WebSocket ──→ ws.py ──→ 3秒窗口缓冲 ──→ TimescaleDB (candles_1m)
   │
   ├── REST API ──→ metrics.py ──→ 批量写入 ──→ TimescaleDB (metrics_5m)
   │
   └── ZIP Files ──→ backfill.py ──→ COPY 写入 ──→ TimescaleDB
```

## 日志

```bash
tail -f logs/backfill.log   # 数据补齐日志
tail -f logs/ws.log         # WebSocket 日志
tail -f logs/metrics.log    # 期货指标日志
```

## 常见问题

### IP 被 Ban (418/429)

系统自动检测并等待解除。如需手动：
```bash
# 查看日志中的 ban 解除时间
grep "ban" logs/*.log

# 降低并发
MAX_CONCURRENT=1 ./scripts/start.sh start
```

### WebSocket 连接失败

```bash
# 检查代理
curl -x http://127.0.0.1:7890 https://fapi.binance.com/fapi/v1/ping

# 设置环境变量
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

### 数据库连接失败

```bash
# 检查端口
ss -tlnp | grep 5433

# 测试连接
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data -c "SELECT 1"
```
