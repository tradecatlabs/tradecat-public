---
name: tradecat-public
description: "TradeCat public terminal skill: operate the bundled user-side TradeCat project, inspect public Google Sheets CSV snapshot caches, run CLI/TUI/export flows, validate installers, and maintain the cache-first no-database contract."
---

# tradecat-public Skill

Use this skill when working on the bundled TradeCat public consumer project stored under `scripts/project/`.

## When to Use This Skill

Trigger when any of these applies:
- The user asks to run, install, debug, validate, or modify TradeCat public terminal behavior.
- The task mentions TradeCat cache, dataset registry, Google Sheets CSV, `event_stream`, CLI/TUI, installer, uninstall, or one-shot request script.
- The task needs the project contracts for cache-first TUI, local JSON snapshots, structured `latest.*` files, or zero-install public requests.

## Not For / Boundaries

- Do not connect to or write TradeCat server PostgreSQL.
- Do not add SQLite, SQL query layers, database repair, vacuum, or server production-chain coupling.
- Do not commit credentials, Google keys, private `.env` files, generated cache files, or local runtime files.
- Keep the skill root clean: project source and project docs live in `scripts/project/`; long-form skill references live in `references/`.

## Quick Reference

### Project Location

```bash
cd scripts/project
```

### Validate Everything

```bash
bash scripts/verify.sh
```

From the skill root:

```bash
bash scripts/verify.sh
```

### Run CLI From Source

```bash
cd scripts/project
PYTHONPATH=src python3 -m tradecat_terminal --help
PYTHONPATH=src python3 -m tradecat_terminal status --json
```

### One-shot Public Request

```bash
python3 scripts/project/scripts/request.py --datasets
python3 scripts/project/scripts/request.py event_stream --format jsonl --limit 5
```

### Inspect Cache Paths

```bash
cd scripts/project
PYTHONPATH=src python3 -m tradecat_terminal path event_stream --json
```

## Project Layout

```text
tradecat-public/
|-- README.md
|-- AGENTS.md              # local-only when present, ignored by Git
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   |-- index.md
|   |-- architecture.md
|   |-- cache-contract.md
|   |-- tui-contract.md
|   `-- install-uninstall.md
`-- scripts/
    |-- verify.sh
    |-- run-tradecat.sh
    `-- project/
        |-- pyproject.toml
        |-- scripts/
        |-- src/
        `-- tests/
```

## References

- `references/index.md`: navigation.
- `references/architecture.md`: project purpose, forbidden paths, and data flows.
- `references/cache-contract.md`: local JSON cache and structured latest file contract.
- `references/tui-contract.md`: TUI rendering, probing, and terminal compatibility rules.
- `references/install-uninstall.md`: installer, launcher, update, and uninstall constraints.

## Examples

### Example 1: Validate The Bundled Project

- Input: "Run the TradeCat checks."
- Steps:
  1. Run `bash scripts/verify.sh` from the skill root.
  2. If lint is needed, run `cd scripts/project && ruff check src tests`.
- Expected output / acceptance: compileall and pytest pass; lint passes when dev dependencies are installed.

### Example 2: Inspect Local Cache Paths

- Input: "Show me where event_stream cache files live."
- Steps:
  1. Run `bash scripts/run-tradecat.sh path event_stream --json`.
  2. Read `latest_json`, `latest_jsonl`, `latest_csv`, and `stream_events`.
- Expected output / acceptance: paths point under `scripts/project/.tradecat/cache` unless `TRADECAT_CACHE_DIR` overrides them.

### Example 3: Modify TUI Behavior

- Input: "Change the TUI probe interval behavior."
- Steps:
  1. Read `references/tui-contract.md`.
  2. Edit `scripts/project/src/tradecat_terminal/tui.py`.
  3. Add or adjust focused tests in `scripts/project/tests/test_cache_tui.py`.
  4. Run `bash scripts/verify.sh`.
- Expected output / acceptance: cache-first startup, background probe, failure backoff, and plain fallback contracts remain intact.

## Maintenance

- Source project: `scripts/project/`
- Validation: `bash scripts/verify.sh`
- Skill root should remain an operator entrypoint, not a second copy of the project.
