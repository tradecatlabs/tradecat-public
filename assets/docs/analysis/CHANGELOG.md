# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Backtest engine (planned)
- Strategy DSL (planned)
- Web Dashboard (planned)

---

## [0.5.0] - 2026-01-16

### Added
- **API Service** - New CoinGlass-compatible REST API (`services/consumption/api-service`, migrated from legacy `services-preview`)
  - **`e591f3df`** feat(api): 添加 api-service 并修复 telegram-service psutil 依赖
  - **`bdc8c88c`** refactor(api): 对齐 CoinGlass API V4 规范
  - **`5e25bd7f`** feat(api): 继承全局 SYMBOLS_GROUPS 配置
  - FastAPI 实现，支持 TimescaleDB (5433) 和 SQLite 数据源
  - 对齐 CoinGlass API V4 规范，Breaking changes:
    - 端点路径变更 (移除 /v1/，添加 /futures/ 前缀)
    - 响应格式: `{code, msg, data, success}`
    - Symbol 支持 BTC/BTCUSDT 格式
    - 时间字段使用毫秒，数值字段使用字符串
  - 新端点:
    - `GET /api/futures/supported-coins` - 支持的币种列表
    - `GET /api/futures/ohlc/history` - K线历史数据
    - `GET /api/futures/open-interest/history` - 持仓量历史
    - `GET /api/futures/funding-rate/history` - 资金费率历史
    - `GET /api/futures/metrics` - 市场指标
    - `GET /api/indicator/list` - 技术指标列表
    - `GET /api/indicator/data` - 技术指标数据
    - `GET /api/signal/cooldown` - 信号冷却状态
  - 继承全局 SYMBOLS_GROUPS 配置
  - 添加 API 调用示例文档和 CoinGlass V4 对比文档

### Documentation
- **`c1b90038`** docs(api): 添加变更日志文档 (改动1.md)
- **`d4d6d1fd`** docs(api): 添加 API 调用示例文档

### Fixed
- **`60571d28`** fix(telegram): 移除 cards registry 中的重复 query.answer()
- **`06ffd4cd`** fix(telegram): 移除重复的 query.answer() 调用
  - 修复 app.py: set_lang_, signal_menu, admin_menu, market_sentiment, single_query_, ranking_menu_nop
  - 修复 vis_handler.py: vis_nop, vis_menu, vis_tpl_, vis_sym_, vis_itv_
  - 修复 signals/ui.py: sig_* handlers
  - 修复 ai_integration.py: handle_interval_selection, handle_coin_selection, _handle_prompt_selected
  - 所有即时响应现在由 app.py callback_query handler 统一处理
- **`a6cc176a`** fix(api): 统一参数校验错误响应格式

---

## [0.4.0] - 2026-01-15

### Added
- **`fbb170b6`** feat(telegram): 为所有按钮回调添加统一即时响应
  - 在 button_callback 入口添加全局 query.answer() 带详细提示
  - 添加 i18n 键: loading.*, progress.*, done.* (zh_CN/en)
  - 从 38 个卡片文件中移除冗余的 query.answer()
  - 响应类型按操作分类:
    - AI 分析: 🤖 启动AI分析...
    - 可视化: 📈 正在渲染图表...
    - 数据加载: 📊 正在加载数据...
    - 刷新: 🔄 正在刷新...
    - 查询: 🔍 正在查询...
    - 切换: ✅ 已切换
    - 菜单导航: 静默
- **`d10e33fc`** feat(telegram): 增强 bot handlers 和卡片服务
  - 更新 en/zh_CN 语言文件
  - 重构 app.py bot handlers
  - 改进 non_blocking_ai_handler
  - 增强 data_provider 和 ranking service
  - 更新资金费率卡片
- **`dd1be2c5`** refactor(trading): 更新异步全量引擎

### Fixed
- **`77c15a28`** fix(cards): 修复 EMA parse_mode 和 KDJ settings 签名
- **`173560ac`** fix(security): 添加 env manager 硬开关并改进错误处理

### Changed
- **`3490919c`** chore(ai): 更新市场分析 prompts
- **`9e698847`** feat(telegram): 禁用 env manager UI 和命令 (安全考虑)
- **`ff50679d`** chore(docs): 移除过时的文档文件
- **`a420461d`** chore: 更新 gitignore 规则

---

## [0.3.0] - 2026-01-14

### Added
- **`25553a45`** feat(signal): 添加数据新鲜度检查，跳过过时数据
- **`970bf3da`** feat(ai): 升级默认模型至 gemini-3-flash-preview

### Fixed
- **`213aaa9c`** fix(telegram): 修复 futures depth/oi/funding 卡片回调
- **`7561cadb`** fix(signal): sqlite 引擎遵循环境变量 symbol 白名单
- **`fda851d4`** fix(telegram): 加固 ranking 卡片回调
- **`81905f26`** fix(telegram): 禁用 EMA/VWAP 卡片的 markdown 解析避免回调失败
- **`ee5554fe`** fix(trading): 对齐 df columns 到表，避免丢弃其他周期
- **`47b7ff24`** fix(predict-service): 修复 orderbook 过滤器并添加测试

### Changed
- **`63ab0bdb`** chore: 统一 1d 周期和数据修复
- **`3d360968`** chore: 添加 workflow notes 到 .gitignore

### Documentation
- **`3422bd3d`** docs: 添加 Gemini headless 指南和 ProxyCast 配置

---

## [0.2.9] - 2026-01-13

### Fixed
- **`6e9a26af`** fix(telegram): 每个 symbol 独立获取最新行，避免时间戳错开导致丢数据
- **`1e7b9054`** fix(telegram): EMA 卡片使用表数据获取选定周期
- **`ce002947`** fix(telegram): 刷新时按单次获取更新时间戳而非全局最大值
- **`4dd83f60`** fix(telegram): 时间显示仅使用数据集时间戳
- **`93fdf037`** fix(telegram): 显示最后数据时间戳使用数据集时间
- **`7a73845d`** fix(signal): 翻译推送、持久化冷却、转义 sqlite 列名

### Documentation
- **`89d5fa65`** docs: 移除误导性的 --days 365 选项
- **`337f0794`** docs(README_EN): 添加加密货币钱包地址
- **`151471d8`** docs: 更新代币 CA 警告说明，简化钱包地址列表
- **`91de77ef`** docs: 添加免责声明和捐赠地址说明

---

## [0.2.8] - 2026-01-12

### Added
- HuggingFace data download script and deploy prompt

### Fixed
- Remove inline comments from logrotate.conf
- Address deployment audit findings
- Add lang parameter to _load_rows methods
- i18n improvements and daemon health check

### Changed
- Remove dead Binance API code from telegram-service
- Remove Binance API dependency

---

## [0.2.7] - 2026-01-11

### Added
- **Signal Service** - Extract signals module as independent service (129 rules)
- **Fate Service** - Add fate-engine (legacy preview service; directory later removed)
- Symbols config inheritance from config/.env

### Changed
- Decouple ai-service from telegram dependency
- Use signal-service via adapter layer in telegram-service
- Standardize project structure for all services

### Fixed
- Fate-service path management and database module
- Add tests directory with conftest.py for fate-service

---

## [0.2.6] - 2026-01-10

### Added
- **Signal Engine** - TimescaleDB-based signal engine for real-time PG data
- 20 core signal rules for high-value low-noise alerts
- PG signal formatter with clean templates
- Signal history query UI
- Telegram admin config panel and user management
- Sliding window retention plan and DDL script

### Fixed
- SQL injection, event loop, and history vulnerabilities in signals
- Inherit symbols from SYMBOLS_GROUPS env config

### Security
- Signal engine audit reports and security fixes

---

## [0.2.5] - 2026-01-09

### Added
- **Visualization Service** - 6 intraday analysis chart templates
- Bollinger Band zone strip template
- Docker support with improved Dockerfile and entrypoint
- Order book collector with hybrid snapshot storage
- Order_book continuous aggregates (1m/1h)
- Latency monitoring and heartbeat detection for order book collector
- i18n translations for visualization module (zh_CN/en)
- English Wyckoff master prompt for AI

### Fixed
- Docker security and service health checks
- Env UI duplicate icons

---

## [0.2.4] - 2026-01-08

### Added
- i18n support to ranking service and signal UI
- Apply i18n to all 38 ranking cards
- Card i18n helper module with translation functions
- VPVR-ridge OHLC horizontal candlestick format

### Changed
- VPVR-ridge uses joypy.joyplot for standardized ridge rendering
- Split preview services into separate tree (legacy)

### Fixed
- VPVR-ridge OHLC logic corrections
- Add libs/common to ws.py path

---

## [0.2.3] - 2026-01-07

### Added
- bookDepth data import script for markets-service

---

## [0.2.2] - 2026-01-06

### Added
- Query command translations
- VPVR-zone-strip square root normalization for market cap

### Fixed
- Complete query i18n for all entry points

---

## [0.2.1] - 2026-01-05

### Added
- Complete i18n coverage (273 terms, 39/39 cards)
- App.py user messages i18n
- VPVR-zone-strip volume red-green gradient colors
- Matplotlib native legend for VPVR-zone-strip

---

## [0.2.0] - 2026-01-04

### Added
- **Predict Service** - Prediction market service (Node.js)
- Complete signal detection system with 129 rules
- Single token complete TXT export functionality
- K-pattern independent panel (bullish/bearish/neutral classification)
- Main menu token query button
- Token query and AI analysis to persistent keyboard
- AI indicator data compression optimization
- GitHub Actions CI and README Badges
- Issue and PR templates
- SECURITY.md

### Fixed
- Signal service SQL injection prevention (T1)
- User subscription SQLite persistence + callback whitelist verification (T2)
- Singleton thread-safe double-check lock (T3)
- Exception logging instead of silent swallowing (T4)
- Cooldown state SQLite persistence (T5)
- Log level correction debug->warning (T6)
- Token query and AI analysis keyboard response
- Bare except changed to except Exception (multiple services)

### Changed
- Clean up old signal files (engine.py/pusher.py/rules.py)
- Architecture diagram to Mermaid format

### Documentation
- Complete English README_EN.md
- WSL2 configuration guide (10GB memory + mirrored network)
- AI analysis details (Wyckoff methodology/professional prompts/DeepSeek)

---

## [0.1.9] - 2026-01-03

### Added
- **AI Service** - Complete AI analysis service with Wyckoff methodology
- Shared symbols management module
- Proxy manager (runtime retry + 1 hour cooldown)
- SQLite connection pool optimization
- IO/CPU split executor
- TimescaleDB compression strategy optimization
- Environment variable configuration management
- Symbol group management (main4/main6/main20/auto/all)
- High priority configuration - indicators/cards/interval switches
- Data-service backfill configuration
- FUNDING.yml for GitHub Sponsors

### Fixed
- Remove all hardcoded absolute paths
- Unified database default connection string to postgres:postgres
- Remove hardcoded proxy, use HTTP_PROXY environment variable
- Fix .env loading path for all services

### Changed
- Unified configuration management to config/.env
- Simplify resource flow card _load_rows
- Move install.sh to scripts directory
- Indicator safety refactoring - return results with status for insufficient data

### Performance
- SQLite connection reuse
- Batch K-line read/write optimization

---

## [0.1.8] - 2026-01-02

### Added
- Microservice initialization script
- Requirements.txt for all services
- SQLite append write + history retention + ranking deduplication
- Startup daemon script

### Changed
- Delete CSV read logic, unify to SQLite
- Remove libs/common, services fully independent
- Unified database location to assets/database/services/telegram-service/
- Remove telegram-service cross-service dependencies
- Rename crypto_trading_bot.py → main.py
- Delete unused realtime_service/kline_manager/kline_listener
- Remove wide table write logic, keep only market_data.db

### Fixed
- Path audit fixes
- Order-service config directory structure
- DB __init__.py import fixes

---

## [0.1.0] - 2024-01-12

### Added
- **Data Module** (`tradecat.Data`)
  - K-line (OHLCV) data fetching from Binance
  - Support for multiple symbols and intervals
  - Local database support (PostgreSQL/TimescaleDB)
  - Ticker and symbols list API

- **Indicators Module** (`tradecat.Indicators`)
  - 17+ technical indicators with pure Python fallback
  - Trend: SMA, EMA, WMA, MACD, ADX
  - Momentum: RSI, KDJ, CCI, Williams %R, MFI
  - Volatility: ATR, Bollinger Bands, Keltner Channel, Donchian Channel
  - Volume: OBV, VWAP, CVD
  - Optional TA-Lib acceleration

- **Signals Module** (`tradecat.Signals`)
  - Automated signal detection
  - RSI overbought/oversold
  - MACD crossovers and divergences
  - Bollinger Band touches and squeezes
  - KDJ crossovers
  - EMA crossovers
  - Volume spikes
  - Signal summary with bias calculation

- **AI Module** (`tradecat.AI`)
  - Multi-model support: OpenAI, Anthropic, Google, DeepSeek
  - Technical analysis with market context
  - Wyckoff methodology analysis
  - Structured analysis output

- **Configuration** (`tradecat.Config`)
  - Database configuration
  - API credentials management
  - Proxy support
  - Environment variable loading

- **Infrastructure**
  - PyPI package structure (src-layout)
  - Type hints (PEP 561)
  - Comprehensive test suite
  - CI/CD with GitHub Actions
  - Multi-platform support (Linux, macOS, Windows)
  - Python 3.9-3.13 compatibility

### Dependencies
- Core: pandas, numpy, requests
- Optional: ccxt, TA-Lib, sqlalchemy, psycopg
- AI: openai, anthropic, google-generativeai

---

[Unreleased]: https://github.com/tukuaiai/tradecat/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/tukuaiai/tradecat/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/tukuaiai/tradecat/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/tukuaiai/tradecat/compare/v0.2.9...v0.3.0
[0.2.9]: https://github.com/tukuaiai/tradecat/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/tukuaiai/tradecat/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/tukuaiai/tradecat/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/tukuaiai/tradecat/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/tukuaiai/tradecat/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/tukuaiai/tradecat/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/tukuaiai/tradecat/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/tukuaiai/tradecat/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/tukuaiai/tradecat/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/tukuaiai/tradecat/compare/v0.1.9...v0.2.0
[0.1.9]: https://github.com/tukuaiai/tradecat/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/tukuaiai/tradecat/compare/v0.1.0...v0.1.8
[0.1.0]: https://github.com/tukuaiai/tradecat/releases/tag/v0.1.0
