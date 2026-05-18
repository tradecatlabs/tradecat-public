# Hermes / Agent 使用指南

本指南是给人和 Hermes/Agent 同时看的操作说明。机器主契约始终是 `skills/tradecat-public/agents/manifest.json`。

## 当前定位

`tradecat-public` 是正常 Python 项目根，内嵌 Hermes/Codex Skill 包。它不是实盘交易机器人；它是 public-readonly 信号源 + Agent research loop + 本地 paper/watch 合约层。

- 开发目录：`/home/lenovo/.projects/cat/tradecat-public`
- Skill 入口：`skills/tradecat-public/SKILL.md`
- 机器主契约：`skills/tradecat-public/agents/manifest.json`
- 实现目录：`src/tradecat_sources/` 与 `src/tradecat_auto/`
- 自包含 Binance 资源：`resources/agent_market_context/binance/`
- 本地运行态：`.runtime/auto-paper/`

## 人工最小流程

```bash
cd /home/lenovo/.projects/cat/tradecat-public
git status --short
bash scripts/validate-skill.sh --strict
bash scripts/agent-smoke.sh
bash scripts/verify.sh
```

开发态挂载到 Hermes 时，只挂载 Skill 包，不把运行态提交：

```bash
mkdir -p ~/.hermes/skills
ln -sfn /home/lenovo/.projects/cat/tradecat-public/skills/tradecat-public ~/.hermes/skills/tradecat-public
hermes -s tradecat-public
```

## Agent 最小流程

```bash
python3 -m json.tool skills/tradecat-public/agents/manifest.json >/dev/null
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/run-tradecat.sh soft-layer --json
bash scripts/run-tradecat.sh paper-report --json
bash scripts/start-auto-paper.sh status --json
```

需要执行 paper/watch 时：

```bash
bash scripts/run-tradecat.sh context-audit --input /path/to/agent-market-context.json --json
bash scripts/run-tradecat.sh run-context --input /path/to/agent-market-context.json --mode paper --json
```

Agent 必须显式提供 paper sizing、leverage 和 exits。缺失时 TradeCat 返回结构化拒绝，不开仓。

## 纸面常驻运行态

```bash
bash scripts/start-auto-paper.sh ops-check --json
bash scripts/start-auto-paper.sh start --json
bash scripts/start-auto-paper.sh status --json
bash scripts/start-auto-paper.sh heal --json
bash scripts/start-auto-paper.sh stop --json
```

本地监控：

```bash
python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。监控页面只读 `.runtime/auto-paper/` 和项目公开状态。

## Agent-supplied Market Context

TradeCat 不自己内置抓取所有 Binance 数据。Hermes/Agent 根据仓库内 Binance skill/API 快照和外部 public/read-only 工具，收集 K 线、盘口、资金费率、OI、多空比等上下文，写成：

- `agent_research_cycle.v1`
- `agent_market_context.v1`
- `agent_trade_thesis.v1`
- `position_management_thesis.v1`

每个外部数据项必须包含 source provenance、安全声明和非签名证明。任何 key、secret、signature、listen key、账户、订单、杠杆或保证金修改材料都必须被拒绝。

## 输入信号语义

- `signal_flow`：事件流，按事件 ID / 内容哈希去重，重复旧表不重复触发开仓。
- `anomaly_panel`：快照面板，必须读取所有榜单/行，按交易对聚合当前状态，不只读第一行。
- 长时间没有新事件时，Agent loop 可以主动执行观察轮，只更新报告或 mark-to-market，不凭空生成新仓位。

## 交付检查

1. `git status --short` 没有意外运行态或私密文件。
2. 新入口在 `manifest.json` 有风险等级、schema/version 和 safety boundary。
3. 新输出有 schema 与测试。
4. Agent context 先 `context-audit`，再 `run-context`。
5. paper runtime 只写 `.runtime/`。
6. 验证命令至少覆盖 `agent-smoke`、`verify`、`validate-skill --strict`。
