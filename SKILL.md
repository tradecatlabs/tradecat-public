---
name: tradecat-public
description: "TradeCat public terminal skill: operate the bundled user-side TradeCat project, inspect public Google Sheets CSV snapshot caches, run CLI/TUI/export flows, validate installers, govern the Skill root vs scripts/project layout, and maintain the cache-first no-database contract."
---

# tradecat-public Skill

Use this skill when working on the bundled TradeCat public consumer project stored under `scripts/project/`.

## When to Use This Skill

Trigger when any of these applies:
- The user asks to run, install, debug, validate, or modify TradeCat public terminal behavior.
- The task mentions TradeCat cache, dataset registry, Google Sheets CSV, `event_stream`, CLI/TUI, installer, uninstall, or one-shot request script.
- The task needs the project contracts for cache-first TUI, local JSON snapshots, structured `latest.*` files, or zero-install public requests.
- The task asks to reorganize, audit, or optimize the Skill wrapper, root files, references, `AGENTS.md`, or the `scripts/project/` project boundary.

## Not For / Boundaries

- Do not connect to or write TradeCat server PostgreSQL.
- Do not add SQLite, SQL query layers, database repair, vacuum, or server production-chain coupling.
- Do not commit credentials, Google keys, private `.env` files, generated cache files, or local runtime files.
- Keep the skill root clean: project source and project docs live in `scripts/project/`; long-form skill references live in `references/`.
- Do not add root `assets/` or `assets/examples/`; project examples, if ever needed, belong under `scripts/project/` and must be documented.

## Quick Reference

### Project Location

```bash
cd scripts/project
```

### Validate Skill And Project

```bash
bash scripts/verify.sh
```

### Bootstrap Development Environment

```bash
bash scripts/bootstrap-dev.sh
```

### Validate Project Only

```bash
cd scripts/project
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

### Audit The Root Boundary

```bash
test ! -e assets
git ls-files | sort
bash scripts/project/scripts/guard_public_local_files.sh
```

### Skill Quality Gate

```bash
bash scripts/validate-skill.sh --strict
```

### Secret Scan

```bash
bash scripts/security-scan.sh
```

### Supply-chain Audit

```bash
bash scripts/supply-chain-audit.sh
```

### Data Contract Check

```bash
cd scripts/project
PYTHONPATH=src python3 scripts/validate_data_contract.py --remote --timeout 10
```

## Project Layout

```text
tradecat-public/
|-- README.md
|-- AGENTS.md              # tracked root governance contract
|-- .pre-commit-config.yaml
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   |-- index.md
|   |-- architecture.md
|   |-- cache-contract.md
|   |-- linear-flows.md
|   |-- tui-contract.md
|   |-- quality-gate.md
|   `-- install-uninstall.md
`-- scripts/
    |-- verify.sh
    |-- bootstrap-dev.sh
    |-- security-scan.sh
    |-- supply-chain-audit.sh
    |-- install-security-tools.sh
    |-- clean-local-runtime.sh
    |-- run-tradecat.sh
    `-- project/
        |-- AGENTS.md
        |-- DEBUG.md
        |-- DEBUG.archive.md
        |-- pyproject.toml
        |-- scripts/
        |-- src/
        `-- tests/
```

## References

- `references/index.md`: navigation.
- `references/architecture.md`: project purpose, forbidden paths, and data flows.
- `references/cache-contract.md`: local JSON cache and structured latest file contract.
- `references/linear-flows.md`: public six-flow map for cache, TUI, one-shot request, install, uninstall, and export/config flows.
- `references/tui-contract.md`: TUI rendering, probing, and terminal compatibility rules.
- `references/install-uninstall.md`: installer, launcher, update, and uninstall constraints.
- `references/quality-gate.md`: pre-delivery checklist for Skill wrapper and bundled project changes.
- `references/release.md`: release evidence, fixed-ref install commands, known limits, and rollback.

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

### Example 4: Optimize The Skill Wrapper

- Input: "Use auto-skill to optimize this skill and fill missing files."
- Steps:
  1. Read `SKILL.md`, `references/index.md`, and `references/quality-gate.md`.
  2. Keep root files limited to Skill/Git metadata, references, and thin scripts.
  3. Put project source, tests, installers, and project README under `scripts/project/`.
  4. Run the strict skill validator and `bash scripts/verify.sh`.
- Expected output / acceptance: `SKILL.md` remains short and actionable, references are navigable, root remains clean, and project validation passes.

## Maintenance

- Source project: `scripts/project/`
- Validation: `bash scripts/verify.sh` from the Skill root; run `bash scripts/validate-skill.sh --strict` when only the Skill gate is needed.
- Skill root should remain an operator entrypoint, not a second copy of the project.
