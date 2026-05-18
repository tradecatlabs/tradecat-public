# Hermes / Agent 使用指南

本指南是给人和 Hermes/Agent 同时看的操作说明。人类先用它确认开发/生产边界、安装方式和安全边界；Hermes/Agent 先用它找到 canonical machine contract、只读入口、Agent-supplied market context 文件格式和验证命令。

## 当前定位

`tradecat-public` 当前是正常 Python 项目根，内嵌一个 Hermes/Codex Skill 包；它不是一个会自动真实下单的交易机器人。

- 开发目录：`/home/lenovo/.projects/cat/tradecat-public`。
- Hermes skill 名：`tradecat-public`。
- Hermes 安装位置：`~/.hermes/skills/tradecat-public` 可指向本仓的 `skills/tradecat-public/`，同时保留仓库根项目作为命令工作目录。
- Skill 入口：`skills/tradecat-public/SKILL.md`。
- 机器主契约：`skills/tradecat-public/agents/manifest.json`。
- Skill 包治理说明：`skills/tradecat-public/references/skill-package-governance.md`。
- 长契约：`skills/tradecat-public/references/agent-contract.md`。
- 本地工具实现：仓库根项目的 `src/`、`contracts/`、`resources/`、`scripts/`、`tests/`。
- 本地运行态：`.runtime/`、`.tradecat/`，这些目录只在本机存在，不提交。

当前开发只在 `/home/lenovo/.projects/cat/tradecat-public` 内进行。生产使用时，再把已经验证过的仓库复制、克隆或软链接到目标环境的 `~/.hermes/skills/tradecat-public`。

## 给人的最小流程

### 1. 在开发目录中工作

```bash
cd /home/lenovo/.projects/cat/tradecat-public
git status --short
```

不要在旧的 `tradecat-auto` 私有目录或生产 skill 目录里直接开发。当前仓库根目录是 Python 项目根；Skill 激活材料在 `skills/tradecat-public/`。

### 2. 开发态挂载到 Hermes

开发期间推荐用软链接，让 Hermes 直接读取当前开发仓：

```bash
mkdir -p ~/.hermes/skills
ln -sfn /home/lenovo/.projects/cat/tradecat-public/skills/tradecat-public ~/.hermes/skills/tradecat-public
hermes -s tradecat-public
```

如果需要生产态隔离，不要软链接开发仓；改用固定 ref 的 clone/copy：

```bash
rm -rf ~/.hermes/skills/tradecat-public
git clone https://github.com/tukuaiai/tradecat.git ~/.projects/tradecat-public
ln -sfn ~/.projects/tradecat-public/skills/tradecat-public ~/.hermes/skills/tradecat-public
```

### 3. 人工验收

```bash
bash scripts/validate-skill.sh --strict
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
```

只改文档时，至少运行 `validate-skill.sh --strict`、`agent-smoke.sh` 和 `verify.sh`；涉及依赖、安装、发布或安全边界时，再运行安全扫描和供应链审计。

## 给 Hermes/Agent 的最小流程

Hermes/Agent 必须把 `skills/tradecat-public/agents/manifest.json` 当作唯一机器入口，不要把 `skills/tradecat-public/agents/hermes.yaml` 或 `skills/tradecat-public/agents/openai.yaml` 当成第二份真实契约。

安全默认顺序：

```bash
python3 -m json.tool skills/tradecat-public/agents/manifest.json >/dev/null
bash scripts/run-tradecat.sh status --json
bash scripts/run-tradecat.sh datasets --json
bash scripts/run-tradecat.sh path signal_flow --json
bash scripts/run-tradecat.sh analyze --json
bash scripts/run-tradecat.sh features --json
python3 scripts/request.py signal_flow --format json --limit 5
```

需要 Agent-supplied market context 时，先审计，再进入 paper/watch：

```bash
bash scripts/run-tradecat.sh auto context-audit --input /path/to/agent-market-context.json --json
bash scripts/run-tradecat.sh auto run-context --input /path/to/agent-market-context.json --mode paper --agent-margin-usdt <agent_decision> --paper-leverage <agent_decision> --json
bash scripts/run-tradecat.sh auto replay-report --archive-path .runtime/cycles.jsonl --ledger-path .runtime/paper_ledger.json --json
```

`auto soft-layer --json` 也会暴露 `role_profiles[].id=discretionary_futures_trader`；它是可配置的 paper-only 交易员提示词。TradeCat 默认不设 paper margin budget/cap、固定保证金、名义价值或杠杆上限；缺少 Agent sizing 必须变成 `WATCH_ONLY` / `agent_sizing_required`。止损、止盈和最大持仓时间也不再有固定默认值，只有 `agent_trade_thesis` 明确给出 `invalidation_price` / `take_profit_price` / `max_holding_minutes`，或本地 operator 提供 `paper_autonomy_profile.v1` 生成 paper-only sizing/exits 时才进入 paper ledger。若 thesis/profile 明确设置 `allow_agent_direction_override=true`，Agent 只可覆盖 `direction_conflict` 这类软方向冲突，不能覆盖低分、kill switch、组合风控或真实交易边界；该 profile 仍必须保持 `real_orders=false`、`signed_requests=false`、`reads_api_keys=false`。

## 纸面生产运行态与审计报告

持续 paper/watch 服务的默认运行态目录是 `.runtime/auto-paper/`，包含 `service_state.json`、`paper_ledger.json`、`cycles.jsonl`、`paper_audit.sqlite3`、`paper-run-loop.log` 和 PID/heartbeat 文件；这些都是本地运行态，已被 `.gitignore` 隔离，不得提交。先用 status 检查，再启动或停止：

```bash
bash scripts/start-auto-paper.sh ops-check --json
bash scripts/start-auto-paper.sh status --json
bash scripts/start-auto-paper.sh start --json
bash scripts/start-auto-paper.sh heal --json
bash scripts/start-auto-paper.sh stop --json
bash scripts/monitor-auto-paper.sh --interval 5
```

连续 paper 服务默认不会自动启动；只有 operator 明确要求本地运行态时才执行
`start` 或 `run-loop --once`。`service_state.json.seen_event_ids` 是去重边界，
同一个 `event_id` 第二次进入服务时只做既有 paper position mark-to-market，不会重复开仓。
observe-only `research-cycle --output-dir` 草案应写入独立目录，不得写入
`.runtime/auto-paper/`，避免和 paper ledger/archive/journal 混写。

运行态报告统一保持 public/read-only + paper/watch：

```bash
bash scripts/run-tradecat.sh auto audit-journal --json
bash scripts/run-tradecat.sh auto health-report --json
bash scripts/run-tradecat.sh auto daily-report --json
bash scripts/run-tradecat.sh auto alert-payload --kind daily --json
```

这些命令只读取本地 paper ledger、cycle archive、SQLite audit journal 和 heartbeat；不会读取 Binance key、不会签名、不会查真实账户/订单、不会真实下单。`audit-journal` 输出 `tradecat_auto.audit_journal_summary.v1`，`health-report` 输出 `tradecat_auto.production_health.v1`，`daily-report` 输出 `tradecat_auto.daily_paper_report.v1`，`alert-payload` 输出 `tradecat_auto.telegram_alerts.v1`。

只有明确需要本地运行态时，才执行会写 `.runtime/` 或 `.tradecat/` 的命令，例如 `sync`、`run-loop --once`、`start-auto-paper.sh start`。当目标是 autonomous paper/watch trader 时，`auto-paper` 应由 Hermes/operator 常驻看护，`not_running` 或 `heartbeat_stale` 是运行阻塞而不是正常完成态。执行后台服务前先跑 `ops-check`，再查状态；需要自愈时用 `heal`，停止时用匹配的 stop 命令。外接 HDMI/终端窗口可运行 `monitor-auto-paper.sh` 作为只读观察屏。完整运维依赖链见 `references/autonomous-paper-ops.md`。

## Agent-supplied market context 输入契约

TradeCat 不要求自己内置抓取所有 Binance 数据。Hermes/Agent 可以根据已安装的 Binance skill、API 文档和工具链，自主获取 public/read-only 的 K 线、盘口、资金费率、OI、多空比、主动买卖量等上下文，然后把结果写成一个本地 JSON 文件交给 TradeCat。

输入文件必须使用：

- 可选顶层研究循环：`schema=tradecat_auto.agent_research_cycle.v1`，schema 文件为 `contracts/tradecat-auto-agent-research-cycle.schema.json`；它只描述信号、public/read-only 工具计划/结果、上下文、thesis、风险备注和下一步动作，不是真实订单。
- 可选纸面仓位管理 thesis：`schema=tradecat_auto.position_management_thesis.v1`，schema 文件为 `contracts/tradecat-auto-position-management-thesis.schema.json`；默认应为 `hold`/`noop`，只有 Agent 明确给出 reason、provenance 和 paper-only intent 时才允许表达 close、adjust_exit、add 或 reduce。
- 可选组合风控 policy：`schema=tradecat_auto.portfolio_risk_policy.v1`，schema 文件为 `contracts/tradecat-auto-portfolio-risk-policy.schema.json`；它只能表达拒绝限制和暂停条件，不能提供订单金额、杠杆、止损、止盈或持仓时间默认值。
- `schema=tradecat_auto.agent_market_context.v1`
- `schema_version=1.0.0`
- `mode` 只能是 `public_readonly`、`paper` 或 `watch`
- `provenance.source_manifest` 指向本仓自包含来源清单
- `market_data[]` 每项必须是 `GET`、非签名、非账户、非订单接口
- 禁止出现 API key、secret、signature、listen key、私钥或任何真实账户材料

已有本地 paper 仓位时，Agent 应先读取 `auto paper-report --json` 的
`paper_account_state`，再用 `position_management_thesis.v1` 表达 `hold`、
`close` 或 `adjust_exit`。应用入口是
`bash scripts/run-tradecat.sh auto position-manage --thesis-path <thesis.json> --json`；
当前 `add/reduce` 只作为显式 intent 契约保留，应用层会 fail-closed，直到有
单独 partial-fill / add-position paper contract。

最小示例：

```json
{
  "schema": "tradecat_auto.agent_market_context.v1",
  "schema_version": "1.0.0",
  "symbol": "BTCUSDT",
  "mode": "paper",
  "generated_at": "2026-05-15T00:00:00Z",
  "provenance": {
    "agent": "hermes",
    "source_manifest": "resources/agent_market_context/binance/provenance.manifest.json"
  },
  "market_data": [
    {
      "family": "klines",
      "endpoint": "/fapi/v1/klines",
      "method": "GET",
      "ok": true,
      "requires_signature": false,
      "signed": false,
      "provenance": {
        "base_url": "https://fapi.binance.com",
        "doc_source": "bundled_binance_reference_snapshot"
      },
      "data": []
    }
  ]
}
```

允许的 family/endpoint 以 `src/tradecat_auto/agent_market_context.py` 和 `contracts/tradecat-auto-agent-market-context.schema.json` 为准；来源资源以 `resources/agent_market_context/binance/provenance.manifest.json` 为准。

## 安全边界

全链路当前只允许 public/read-only 与 paper/watch：

- 不读取 Binance API key。
- 不签名请求。
- 不读取真实账户、余额、仓位或订单。
- 不调用 order/account/listenKey/leverage/margin 等真实账户或交易接口。
- 不真实下单。
- 不把 `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/` 或私密 `.env` 提交到 Git。

如果 Agent 提供了签名字段、账户接口、订单接口或凭证样式字段，`context-audit` 必须拒绝，`run-context` 不得继续进入 paper pipeline。
本地 paper 新开仓可用 `--paper-kill-switch-path <local-file>` 或
`TRADECAT_AUTO_PAPER_KILL_SWITCH_PATH` 暂停；文件存在时只拒绝 paper/watch
新仓，不会触达 Binance 账户或订单接口。`portfolio_risk_policy.v1` 中的
`abnormal_move_halt_bps`、`new_entries_enabled=false` 和 `kill_switch.active=true`
同样只影响本地 paper/watch 风控拒绝。

## 文档入口分工

- `README.md`：给人看的仓库定位、开发/生产边界、快速入口和目录说明。
- `skills/tradecat-public/SKILL.md`：Hermes 加载 skill 后最先读到的短指令。
- `skills/tradecat-public/agents/manifest.json`：机器可读主契约，包含命令、schema、风险等级、路径和安全边界。
- `skills/tradecat-public/references/skill-package-governance.md`：Skill 包形态、根目录职责、内部项目边界、Agent/交易员 role profile 和运行态隔离规则。
- `skills/tradecat-public/references/agent-contract.md`：Agent 长契约，解释 JSON envelope、错误码、风险等级和自动化入口。
- `skills/tradecat-public/references/hermes-agent-guide.md`：本指南，连接人类操作与 Hermes/Agent 执行协议。
- `README.md`：用户侧 TradeCat CLI/TUI/auto 工具说明。

## 交付前检查清单

1. `git status --short` 没有意外运行态或私密文件。
2. `skills/tradecat-public/agents/manifest.json` 可被 `python3 -m json.tool` 解析。
3. 新增文档已经进入 `skills/tradecat-public/references/index.md`、`README.md`、`skills/tradecat-public/SKILL.md` 或 `skills/tradecat-public/agents/manifest.json` 中至少一个入口。
4. 新命令有 risk class、schema/version、exit code 和 safety boundary。
5. 新 schema 有 `schema` / `schema_version`，并有测试或验证入口。
6. 涉及 Agent-supplied market context 时，`context-audit` 先于 `run-context`。
7. 涉及 paper runtime 时，只写 ignored 的 `.runtime/` 或 `.tradecat/`。
