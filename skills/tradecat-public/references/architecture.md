# Architecture

`tradecat-public` is the repository-root Python project for a headless Agent paper-trading runtime. It embeds a Hermes/Codex Skill package under `skills/tradecat-public/`. The Skill package is activation and contract metadata; implementation lives in the repository root.

## Directory Shape

```text
tradecat-public/
|-- README.md
|-- AGENTS.md
|-- pyproject.toml
|-- constraints.txt
|-- contracts/
|-- resources/
|   |-- agent_market_context/
|   `-- agent_soft_layer/
|-- scripts/
|-- src/
|   |-- tradecat_sources/
|   `-- tradecat_auto/
|-- tests/
|-- tasks/
`-- skills/
    `-- tradecat-public/
        |-- SKILL.md
        |-- agents/
        |-- references/
        `-- scripts/
```

## Mission

Public online sheets provide signals. Agent/Hermes supplies Binance public/read-only market context and trade thesis. TradeCat validates schema/provenance/safety, aligns signals, runs deterministic paper/watch, records ledger/audit evidence, and emits health/daily/replay reports.

Retired product surfaces: local interactive TUI, installer/uninstaller, watchdog, cache browser, analysis report, feature bundle, and `tradecat_terminal`.

## Source Boundaries

- `src/tradecat_sources/`: public online sheet registry, dataset contract loading, CSV fetch/parse helpers, and zero-install request support.
- `src/tradecat_auto/`: Agent market context audit, research cycle, thesis parsing, risk, strategies, paper broker, paper ledger, service loop, replay, health, daily, alert, and monitor-facing reports.
- `resources/agent_market_context/binance/`: self-contained readonly Binance skill/API snapshots with provenance manifest.
- `resources/agent_soft_layer/`: Agent role prompts and endpoint policy.
- `contracts/`: JSON schemas for Agent, request, dataset, paper/watch, audit, risk, and report payloads.
- `scripts/`: thin CLI wrappers, request entrypoint, local paper lifecycle, web monitor, validation, security, and supply-chain checks.
- `skills/tradecat-public/`: Skill activation files, Agent profiles, manifest, references, and thin wrappers only.

## Data Flow

```text
signal_flow / anomaly_panel
-> scripts/request.py / tradecat_sources
-> Agent/Hermes public-readonly research
-> agent_market_context.v1 + agent_trade_thesis.v1
-> context-audit
-> run-context / run-loop
-> paper risk gate
-> paper_broker / paper_ledger
-> .runtime/auto-paper cycles + SQLite audit journal
-> health / daily / alert / replay reports
```

## Forbidden Paths

- No root `SKILL.md`, `agents/`, or `references/`.
- No `src/tradecat_terminal/`.
- No `install.sh`, `install.ps1`, `uninstall.sh`, `uninstall.ps1`.
- No `scripts/start.sh` or `scripts/watchdog.sh`.
- No tracked `.runtime/`, `.tradecat/`, `.venv/`, `.hermes/`, `.tools/`, credentials, caches, ledgers, audit journals, or private env files.
- No Binance signed/account/order/listenKey/leverage/margin code path in the public repo.

## Documentation Map

- `README.md`: concise root project guide.
- `AGENTS.md`: repository governance and architecture memory.
- `skills/tradecat-public/SKILL.md`: Skill activation guide.
- `skills/tradecat-public/agents/manifest.json`: canonical machine contract.
- `skills/tradecat-public/references/agent-contract.md`: Agent contract details.
- `skills/tradecat-public/references/hermes-agent-guide.md`: operating guide.
- `skills/tradecat-public/references/quality-gate.md`: validation and delivery gate.

Any architecture change must update `README.md`, `AGENTS.md`, `SKILL.md`, `manifest.json`, and the relevant reference file in the same patch.
