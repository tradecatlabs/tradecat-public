# Telegram Service

加密市场情报 Telegram 机器人，提供排行榜卡片、单币快照、信号订阅等功能。

## 功能

| 功能 | 说明 |
|:---|:---|
| **40+ 排行榜卡片** | 基础/合约/高级三类，支持多周期切换 |
| **单币快照** | 输入 `btc!` 查看单币种多维度数据 |
| **信号订阅** | 用户可订阅指标信号推送 |
| **AI 分析** | 集成 AI 的非阻塞分析（可选） |

## 目录结构

```
src/
├── bot/
│   ├── app.py                  # 主入口，路由，状态管理
│   ├── single_token_snapshot.py # 单币快照渲染
│   ├── signal_formatter.py     # 信号文案格式化
│   └── non_blocking_ai_handler.py # 异步 AI 处理
├── cards/
│   ├── basic/                  # 基础指标卡片
│   ├── futures/                # 合约指标卡片
│   ├── advanced/               # 高级指标卡片
│   ├── data_provider.py        # PG 数据读取（tg_cards）
│   ├── 排行榜服务.py           # 排行榜生成
│   └── registry.py             # 卡片注册表
├── utils/
│   └── paths.py                # 路径工具
├── config/
└── main.py                     # 入口
```

## 快速开始

### 环境要求

- Python >= 3.10
- 指标数据源：PostgreSQL（`DATABASE_URL` 指向的库内 `tg_cards.*`）

### 安装

```bash
# 方式一：使用初始化脚本
cd /path/to/tradecat
./scripts/init.sh telegram-service

# 方式二：手动安装
cd services/consumption/telegram-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 配置

```bash
cp assets/config/.env.example assets/config/.env
vim assets/config/.env
# 设置 TELEGRAM_BOT_TOKEN
```

### 启动

```bash
# 前台运行
python -m src

# 后台运行
nohup python -m src > logs/bot.log 2>&1 &

# 或使用守护进程（从项目根目录）
cd /path/to/tradecat
./scripts/start.sh start
```

## 配置说明

### 环境变量 (assets/config/.env)

| 变量 | 必填 | 说明 |
|:---|:---:|:---|
| `TELEGRAM_BOT_TOKEN` | ✓ | Bot Token |
| `DATABASE_URL` | ✓ | PostgreSQL/TimescaleDB 连接串（需包含 `tg_cards.*`） |
| `INDICATOR_PG_SCHEMA` | - | PG 指标 schema（默认 `tg_cards`，可覆盖） |
| `HTTP_PROXY` | - | HTTP 代理地址 |
| `HTTPS_PROXY` | - | HTTPS 代理地址 |
| `BINANCE_API_DISABLED` | - | 禁用 Binance API (1=禁用) |
| `DEFAULT_LOCALE` | - | 默认语言（zh-CN / en） |
| `SUPPORTED_LOCALES` | - | 支持的语言列表，逗号分隔 |
| `FALLBACK_LOCALE` | - | 翻译缺失时回退语言 |

### .env.example

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
DATABASE_URL=postgresql://user:pass@localhost:5432/market_data
INDICATOR_PG_SCHEMA=tg_cards
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
BINANCE_API_DISABLED=1
DEFAULT_LOCALE=zh-CN
SUPPORTED_LOCALES=zh-CN,en
FALLBACK_LOCALE=zh-CN
```

## 多语言

- 运行中使用 `/lang` 命令弹出语言切换菜单（当前提供 简体中文 / English）。
- 用户语言偏好保存在 `data/user_locale.json`。
- 翻译文件位于 `locales/<lang>/LC_MESSAGES/bot.po`，使用 `msgfmt bot.po -o bot.mo` 编译。

## 卡片列表

### 基础卡片
- KDJ、MACD柱状、OBV、RSI谐波
- 布林带、成交量、成交量比率
- 支撑阻力、资金流向

### 合约卡片
- 持仓排行、OI趋势、OI连续性、OI极值告警
- 主动买卖比、主动成交方向、主动跳变、主动连续性
- 大户情绪、全市场情绪、情绪分歧、情绪动量
- 持仓增减速、期货持仓情绪、波动度
- 翻转雷达、风险拥挤度、市场深度、资金费率、爆仓

### 高级卡片
- ATR、CVD、EMA、K线形态、MFI
- VPVR、VWAP、流动性、超级精准趋势、趋势线

## 数据流

```
Indicator Store
  └─ tg_cards.* (PostgreSQL)
        │
        ▼
    data_provider.py (读取)
        │
        ▼
    cards/*.py (渲染)
        │
        ▼
    Telegram Bot (发送)
```

## 数据来源

Bot 的排行榜/币种查询数据来自指标库（38 张表）：

- PG：`DATABASE_URL` 指向的库内 `tg_cards.*`

## 日志

```bash
tail -f logs/bot.log
```

## 常见问题

### Bot 启动冲突

```
telegram.error.Conflict: Terminated by other getUpdates request
```

确保只有一个 Bot 实例在运行：
```bash
pkill -f "python.*src.main"
python -m src.main
```

### 数据读取为空

1. 确认 `DATABASE_URL` 可连接且存在 `tg_cards.*`（表结构需执行 `assets/database/db/schema/021_tg_cards_sqlite_parity.sql`）
2. 确认 trading-service 已运行并写入数据
3. 查看日志中的 PG 查询错误

### 代理问题

```bash
# 设置代理环境变量
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
python -m src.main
```

### 获取 Bot Token

1. 在 Telegram 中找到 @BotFather
2. 发送 `/newbot` 创建新 Bot
3. 复制 Token 到 `assets/config/.env`
