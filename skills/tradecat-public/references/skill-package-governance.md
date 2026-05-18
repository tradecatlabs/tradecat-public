# Skill Package Governance

TradeCat uses a normal repository-root Python project with an embedded Hermes/Codex Skill package.

## Responsibilities

- Repository root: Python package, contracts, resources, scripts, tests, task docs, and local paper/watch runtime entrypoints.
- `skills/tradecat-public/`: Skill activation, Agent manifest, platform profiles, references, and thin wrappers.
- `skills/tradecat-public/agents/manifest.json`: single machine-readable source of truth for Agent/Hermes.

## Retired Surfaces

The old local terminal product is intentionally removed:

- `src/tradecat_terminal/`
- root `install.sh` / `install.ps1`
- root `uninstall.sh` / `uninstall.ps1`
- `scripts/start.sh`
- `scripts/watchdog.sh`
- interactive TUI/cache-browser flows

Do not recreate them as compatibility layers unless a future task explicitly reverses this architecture decision.

## Allowed Local Runtime

Runtime state may exist only in ignored local paths:

- `.runtime/**`
- `.tradecat/**`
- `.venv/**`
- `.hermes/**`
- `.tools/**`

No runtime file may be committed.

## Safety Contract

The public repo remains public-readonly + paper/watch. It must never contain:

- Binance credentials or secret material.
- Signed request code paths.
- Account/order/listenKey/leverage/margin private endpoint execution.
- Real order execution.
- Default paper sizing/exits invented by TradeCat.

## Validation

```bash
bash scripts/guard_public_local_files.sh
bash scripts/validate-skill.sh --strict
bash scripts/agent-smoke.sh
```
