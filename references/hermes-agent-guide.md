# Hermes / Agent 使用指南

本指南是给人和 Hermes/Agent 同时看的操作说明。人类先用它确认开发/生产边界、安装方式和安全边界；Hermes/Agent 先用它找到 canonical machine contract、只读入口、Agent-supplied market context 文件格式和验证命令。

## 当前定位

`tradecat-public` 当前首先是一个 Hermes skill 包，不是生产运行目录，也不是一个会自动真实下单的交易机器人。

- 开发目录：`/home/lenovo/.projects/cat/tradecat-public`。
- Hermes skill 名：`tradecat-public`。
- Hermes 安装位置：`~/.hermes/skills/tradecat-public`。
- Skill 入口：`SKILL.md`。
- 机器主契约：`agents/manifest.json`。
- 长契约：`references/agent-contract.md`。
- 本地工具实现：`scripts/project/`。
- 本地运行态：`.runtime/`、`scripts/project/.runtime/`、`scripts/project/.tradecat/`，这些目录只在本机存在，不提交。

当前开发只在 `/home/lenovo/.projects/cat/tradecat-public` 内进行。生产使用时，再把已经验证过的仓库复制、克隆或软链接到目标环境的 `~/.hermes/skills/tradecat-public`。

## 给人的最小流程

### 1. 在开发目录中工作

```bash
cd /home/lenovo/.projects/cat/tradecat-public
git status --short
```

不要在旧的 `tradecat-auto` 私有目录或生产 skill 目录里直接开发。当前仓库根目录是 skill 外壳；Python 源码和用户侧工具在 `scripts/project/`。

### 2. 开发态挂载到 Hermes

开发期间推荐用软链接，让 Hermes 直接读取当前开发仓：

```bash
mkdir -p ~/.hermes/skills
ln -sfn /home/lenovo/.projects/cat/tradecat-public ~/.hermes/skills/tradecat-public
hermes -s tradecat-public
```

如果需要生产态隔离，不要软链接开发仓；改用固定 ref 的 clone/copy：

```bash
rm -rf ~/.hermes/skills/tradecat-public
git clone https://github.com/tukuaiai/tradecat.git ~/.hermes/skills/tradecat-public
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

Hermes/Agent 必须把 `agents/manifest.json` 当作唯一机器入口，不要把 `agents/hermes.yaml` 或 `agents/openai.yaml` 当成第二份真实契约。

安全默认顺序：

```bash
python3 -m json.tool agents/manifest.json >/dev/null
bash scripts/run-tradecat.sh status --json
bash scripts/run-tradecat.sh datasets --json
bash scripts/run-tradecat.sh path event_stream --json
bash scripts/run-tradecat.sh analyze --json
bash scripts/run-tradecat.sh features --json
python3 scripts/project/scripts/request.py event_stream --format json --limit 5
```

需要 Agent-supplied market context 时，先审计，再进入 paper/watch：

```bash
bash scripts/run-tradecat.sh auto context-audit --input /path/to/agent-market-context.json --json
bash scripts/run-tradecat.sh auto run-context --input /path/to/agent-market-context.json --mode paper --notional-usdt 12 --json
bash scripts/run-tradecat.sh auto replay-report --archive-path .runtime/cycles.jsonl --ledger-path .runtime/paper_ledger.json --json
```

## 纸面生产运行态与审计报告

持续 paper/watch 服务的默认运行态目录是 `scripts/project/.runtime/auto-paper/`，包含 `service_state.json`、`paper_ledger.json`、`cycles.jsonl`、`paper_audit.sqlite3`、`paper-run-loop.log` 和 PID/heartbeat 文件；这些都是本地运行态，已被 `.gitignore` 隔离，不得提交。先用 status 检查，再启动或停止：

```bash
bash scripts/project/scripts/start-auto-paper.sh status --json
bash scripts/project/scripts/start-auto-paper.sh start --json
bash scripts/project/scripts/start-auto-paper.sh stop --json
```

运行态报告统一保持 public/read-only + paper/watch：

```bash
bash scripts/run-tradecat.sh auto audit-journal --json
bash scripts/run-tradecat.sh auto health-report --json
bash scripts/run-tradecat.sh auto daily-report --json
bash scripts/run-tradecat.sh auto alert-payload --kind daily --json
```

这些命令只读取本地 paper ledger、cycle archive、SQLite audit journal 和 heartbeat；不会读取 Binance key、不会签名、不会查真实账户/订单、不会真实下单。`audit-journal` 输出 `tradecat_auto.audit_journal_summary.v1`，`health-report` 输出 `tradecat_auto.production_health.v1`，`daily-report` 输出 `tradecat_auto.daily_paper_report.v1`，`alert-payload` 输出 `tradecat_auto.telegram_alerts.v1`。

只有明确需要本地运行态时，才执行会写 `.runtime/` 或 `.tradecat/` 的命令，例如 `sync`、`run-loop --once`、`start-auto-paper.sh start`。执行后台服务前先查状态，停止时用匹配的 stop 命令。

## Agent-supplied market context 输入契约

TradeCat 不要求自己内置抓取所有 Binance 数据。Hermes/Agent 可以根据已安装的 Binance skill、API 文档和工具链，自主获取 public/read-only 的 K 线、盘口、资金费率、OI、多空比、主动买卖量等上下文，然后把结果写成一个本地 JSON 文件交给 TradeCat。

输入文件必须使用：

- `schema=tradecat_auto.agent_market_context.v1`
- `schema_version=1.0.0`
- `mode` 只能是 `public_readonly`、`paper` 或 `watch`
- `provenance.source_manifest` 指向本仓自包含来源清单
- `market_data[]` 每项必须是 `GET`、非签名、非账户、非订单接口
- 禁止出现 API key、secret、signature、listen key、私钥或任何真实账户材料

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
    "source_manifest": "scripts/project/resources/agent_market_context/binance/provenance.manifest.json"
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

允许的 family/endpoint 以 `scripts/project/src/tradecat_auto/agent_market_context.py` 和 `scripts/project/contracts/tradecat-auto-agent-market-context.schema.json` 为准；来源资源以 `scripts/project/resources/agent_market_context/binance/provenance.manifest.json` 为准。

## 安全边界

全链路当前只允许 public/read-only 与 paper/watch：

- 不读取 Binance API key。
- 不签名请求。
- 不读取真实账户、余额、仓位或订单。
- 不调用 order/account/listenKey/leverage/margin 等真实账户或交易接口。
- 不真实下单。
- 不把 `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/` 或私密 `.env` 提交到 Git。

如果 Agent 提供了签名字段、账户接口、订单接口或凭证样式字段，`context-audit` 必须拒绝，`run-context` 不得继续进入 paper pipeline。

## 文档入口分工

- `README.md`：给人看的仓库定位、开发/生产边界、快速入口和目录说明。
- `SKILL.md`：Hermes 加载 skill 后最先读到的短指令。
- `agents/manifest.json`：机器可读主契约，包含命令、schema、风险等级、路径和安全边界。
- `references/agent-contract.md`：Agent 长契约，解释 JSON envelope、错误码、风险等级和自动化入口。
- `references/hermes-agent-guide.md`：本指南，连接人类操作与 Hermes/Agent 执行协议。
- `scripts/project/README.md`：用户侧 TradeCat CLI/TUI/auto 工具说明。

## 交付前检查清单

1. `git status --short` 没有意外运行态或私密文件。
2. `agents/manifest.json` 可被 `python3 -m json.tool` 解析。
3. 新增文档已经进入 `references/index.md`、`README.md`、`SKILL.md` 或 `agents/manifest.json` 中至少一个入口。
4. 新命令有 risk class、schema/version、exit code 和 safety boundary。
5. 新 schema 有 `schema` / `schema_version`，并有测试或验证入口。
6. 涉及 Agent-supplied market context 时，`context-audit` 先于 `run-context`。
7. 涉及 paper runtime 时，只写 ignored 的 `.runtime/` 或 `.tradecat/`。
