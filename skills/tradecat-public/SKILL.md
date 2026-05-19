---
name: tradecat-public
description: "TradeCat public Hermes skill: Agent/Hermes paper-trading runtime using public online sheet signals, bundled Binance public-readonly resources, schema-audited context, and local paper/watch execution."
---

# tradecat-public Skill

Use this skill when Hermes/Agent needs to operate TradeCat from the embedded Skill package at `skills/tradecat-public/`. The Python project root is the repository root two levels above this Skill directory; the Skill package provides activation rules, Agent role profiles, references, and the canonical manifest.

## When to Use This Skill

- The task mentions TradeCat public sheet signals, `signal_flow`, `anomaly_panel`, Agent trading loops, paper/watch, paper ledger, replay/backtest, health/daily/alert reports, or autonomous paper ops.
- The task mentions Binance public/read-only Agent market context, K lines, order book, funding, open interest, long/short ratio, context audit, or trade thesis.
- The task needs the Agent machine contract, role profile, safety boundary, Hermes/OpenAI adapter config, or Skill/package governance.

## Not For / Boundaries

- Do not read Binance keys, secrets, listen keys, account state, balances, positions, or orders.
- Do not sign requests, call private account/order/leverage/margin endpoints, or place real orders.
- Do not invent sizing, leverage, stop loss, take profit, or time-stop defaults; Agent thesis must explicitly provide them.
- Do not restore the retired local TUI, installer, watchdog, or cache-browser product line.
- Do not write runtime, cache, logs, ledgers, audit journals, `.env`, `.venv`, `.tradecat`, `.runtime`, `.hermes`, or `.tools` into git.
- TradeCat may write local paper/watch state only under ignored `.runtime/`.

## Quick Reference

From the repository root:

```bash
python3 -m json.tool skills/tradecat-public/agents/manifest.json >/dev/null
python3 scripts/request.py --datasets --format json
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/run-tradecat.sh soft-layer --json
bash scripts/run-tradecat.sh paper-report --json
bash scripts/start-auto-paper.sh status --json
```

From this Skill directory, use the local wrapper:

```bash
bash scripts/run-tradecat.sh soft-layer --json
```

Agent-supplied market context:

```bash
bash scripts/binance-public-bundle.sh --symbols BTCUSDT,ETHUSDT --json
bash scripts/run-tradecat.sh agent-market-context --symbol BTCUSDT --json
bash scripts/run-tradecat.sh context-audit --input /path/to/agent-market-context.json --json
bash scripts/run-tradecat.sh run-context --input /path/to/agent-market-context.json --mode paper --json
bash scripts/run-tradecat.sh replay-report --archive-path .runtime/auto-paper/cycles.jsonl --ledger-path .runtime/auto-paper/paper_ledger.json --json
bash scripts/run-tradecat.sh strategy-review --ledger-path .runtime/auto-paper/paper_ledger.json --archive-path .runtime/auto-paper/cycles.jsonl --json
```

Validation:

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
```

## Examples

### Example 1: Inspect Public Signals

Run `python3 scripts/request.py signal_flow --format json --limit 5`, then inspect `anomaly_panel` with `python3 scripts/request.py anomaly_panel --format json --limit 0`.

### Example 2: Audit Agent Market Context

Run `bash scripts/run-tradecat.sh context-audit --input context.json --json`. Only if the audit passes and the Agent supplied explicit paper sizing/exits should paper/watch execution continue.

### Example 3: Operate Paper Runtime

Run `bash scripts/start-auto-paper.sh ops-check --json`, then `bash scripts/start-auto-paper.sh status --json`. Use `python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port 8765` only for local runtime observation.

### Example 4: Change Project Code

Edit root `src/`, `tests/`, `contracts/`, `resources/`, or `scripts/`; keep Skill activation files under `skills/tradecat-public/`. Update `AGENTS.md` and manifest paths when architecture changes.

## References

- `agents/manifest.json`: canonical machine contract, stored inside this Skill package.
- `references/index.md`: reference navigation.
- `references/skill-package-governance.md`: embedded Skill package governance.
- `references/hermes-agent-guide.md`: Hermes/Agent operating guide.
- `references/agent-contract.md`: Agent command and JSON contract.
- `references/private-executor-boundary.md`: public/private real-execution boundary.

## Maintenance

- Manifest paths are repository-root relative unless explicitly documented otherwise.
- The project root must remain a normal Python project; the Skill package must remain under `skills/tradecat-public/`.
- Keep all safety fields `real_orders=false`, `signed_requests=false`, and `reads_api_keys=false` for public repo entrypoints.
