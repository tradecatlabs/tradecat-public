# TradeCat Public Debug Notes

## 当前真相

- 仓库根目录是唯一 Python 项目根。
- `skills/tradecat-public/` 是内嵌 Hermes/Codex Skill 包，只承载 Skill 激活、Agent manifest、profile 和 references。
- 当前产品形态是 headless Agent paper-trading runtime：公开在线表格信号源 + Agent/Hermes Binance public-readonly context + TradeCat paper/watch 合约层。
- 旧本地 TUI、安装器、watchdog、缓存浏览器、analysis report、feature bundle 和 `tradecat_terminal` 已退役。
- `src/tradecat_sources/` 只负责公开在线表格信号源读取与 dataset contract。
- `src/tradecat_auto/` 负责 Agent market context audit、run-context/run-loop、paper ledger、risk reject、replay、health/daily/alert 报告。
- `skills/tradecat-public/agents/manifest.json` 是唯一机器主契约。
- 运行态只允许在 ignored `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/`、`.tools/`。

## 2026-05-18 大刀阔斧退役本地 TUI 产品线

### 现象

用户目标已从“本地表格终端工具”转为“Agent 交易员同步在线表格作为信号源的自主纸面交易系统”。继续维护 TUI/install/cache-browser 会拉高修改成本，并遮蔽真正的 Agent loop 与 paper/watch 运行态。

### 决策

- 保留 Binance skill/API 文档和 `resources/agent_market_context/binance/` 自包含快照。
- 保留公开在线表格读取能力，但收敛到 `scripts/request.py` 与 `src/tradecat_sources/`。
- 保留并强化 `src/tradecat_auto/` 的 Agent context、paper/watch、ledger、风险、报告和监控。
- 删除旧 `src/tradecat_terminal/`、安装器、watchdog、TUI/cache/browser 相关 contracts/tests/docs。
- 文档和 CI 改为保护 headless Agent runtime 边界。

### 验收

- `bash scripts/guard_public_local_files.sh` 不允许退役路径复活。
- `bash scripts/agent-smoke.sh` 验证 Skill/Agent 快速路径。
- `bash scripts/verify.sh` 验证项目源码、contracts、tests。
- `bash scripts/validate-skill.sh --strict` 验证 Skill 包。
- 安全/供应链扫描继续保证 public repo 无凭证与私有交易代码。

## 禁止回退

- 禁止恢复 `src/tradecat_terminal/`。
- 禁止恢复交互式 TUI 作为默认产品面。
- 禁止恢复 root install/uninstall 脚本或 old watchdog。
- 禁止把在线表格内容当作下单指令；它只是 Agent research signal。
- 禁止在缺 Agent sizing/leverage/exits 时开仓。
- 禁止任何 Binance key、签名、账户、订单、杠杆、保证金或真实下单路径进入 public repo。

## 历史事故索引

旧 SQLite、缓存、TUI、安装器、弱网首屏等事故记录已归档到 `DEBUG.archive.md`。该文件只作为历史复盘材料，不是当前运行契约。
