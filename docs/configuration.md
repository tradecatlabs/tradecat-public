# Configuration

TradeCat Public 的配置原则是少配置、强边界、默认本地隔离。项目不需要也不接受 Binance 凭证。

## 允许的配置

- `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`: public 网络读取代理。
- `TRADECAT_AUTO_PAPER_RUNTIME_DIR`: 本地 paper/watch runtime 目录。
- `TRADECAT_AUTO_PAPER_CYCLE_TIMEOUT_SECONDS`: 单轮 public-readonly/paper cycle 最大运行秒数，防止进程存活但心跳停滞。
- `TRADECAT_AUTO_PAPER_FEE_BPS`: paper 成交手续费 fallback；默认 `4`，表示 Binance USD-M 文档示例 taker 费率，不查询签名账户费率。
- `TRADECAT_AUTO_PAPER_SLIPPAGE_BPS`: 公开盘口不可用时的本地滑点 fallback；默认 `0`，开仓优先用 Binance public depth 估算。
- `TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH`: Agent/Hermes 显式生成的 paper thesis 路径；优先级高于默认 runtime profile。
- `TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED`: 默认 `1`，在 `.runtime/auto-paper/paper_autonomy_profile.json` 生成 paper-only 自治 profile；设置 `0` 时恢复严格等待外部 thesis。
- `TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH`: 可选用户约束 profile 路径；未设置且自治开启时使用 runtime 默认路径。
- `TRADECAT_AUTO_PAPER_AUTONOMY_MARGIN_USDT`: 默认 `10`，runtime profile 的 paper 保证金。
- `TRADECAT_AUTO_PAPER_AUTONOMY_LEVERAGE`: 默认 `1`，runtime profile 的 paper 杠杆。
- `TRADECAT_AUTO_PAPER_AUTONOMY_STOP_LOSS_BPS`: 默认 `150`，runtime profile 的失效价距离。
- `TRADECAT_AUTO_PAPER_AUTONOMY_TAKE_PROFIT_BPS`: 默认 `300`，runtime profile 的目标价距离。
- `TRADECAT_AUTO_PAPER_AUTONOMY_MAX_HOLDING_MINUTES`: 默认 `90`，runtime profile 的最长纸面持仓分钟数。
- `TRADECAT_AUTO_PAPER_AUTONOMY_DIRECTION_POLICY`: 默认 `sheet_signal_or_taker_flow`，优先按在线表格信号方向生成 paper thesis。
- `TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_ENABLED`: 默认 `1`，每轮从本地 paper ledger / cycle archive 生成 runtime `strategy_state.v1`，用于亏损 symbol/信号/方向过滤和持仓上限。
- `TRADECAT_AUTO_PAPER_STRATEGY_STATE_PATH`: 默认 `.runtime/auto-paper/strategy_state.json`。
- `TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_MAX_OPEN_POSITIONS`: 默认 `50`，自我迭代策略状态的最大 open position 上限。
- `TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_MAX_POSITIONS_PER_SYMBOL`: 默认 `3`，自我迭代策略状态的单币最大并发上限。
- `TRADECAT_AUTO_PAPER_EVENT_LIMIT`: 读取 `signal_flow` 行数；默认 `0` 表示不限制。
- `TRADECAT_AUTO_PAPER_MAX_EVENT_AGE_SECONDS`: 可选旧信号过滤；默认留空。
- `TRADECAT_AUTO_PAPER_MONITOR_HOST`: 本地监控监听地址。
- `TRADECAT_AUTO_PAPER_MONITOR_PORT`: 本地监控端口。

## 禁止的配置

- Binance key / secret / listen key。
- 真实账户、订单、杠杆、保证金、余额、持仓私有接口配置。
- 真实下单开关。
- Binance 真实下单开关、签名开关或账户读取开关。

## 示例

`.env.example` 只提供 public-readonly 和本地 runtime 相关变量。真正运行时可以导出环境变量，也可以用私有 `.env`，但 `.env` 必须保持 ignored。
