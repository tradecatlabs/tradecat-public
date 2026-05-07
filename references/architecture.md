# Architecture

`tradecat-public` is a Codex skill wrapper around a bundled user-side TradeCat project.

The Skill root is not the Python project root. It exists to hold Skill metadata,
Git metadata, references, and thin entry scripts.

```text
tradecat-public/
|-- README.md
|-- AGENTS.md                 # tracked root governance contract
|-- .git/                     # Git metadata, hidden, never moved
|-- .github/workflows/ci.yml  # CI metadata, hidden, never moved
|-- .gitignore
|-- SKILL.md
|-- agents/openai.yaml
|-- references/
|   |-- index.md
|   |-- architecture.md
|   |-- cache-contract.md
|   |-- install-uninstall.md
|   |-- linear-flows.md
|   |-- quality-gate.md
|   `-- tui-contract.md
`-- scripts/
    |-- verify.sh
    |-- bootstrap-dev.sh
    |-- security-scan.sh
    |-- run-tradecat.sh
    `-- project/
```

The project itself lives in `scripts/project/` and keeps its original Python package shape:

```text
scripts/project/
|-- AGENTS.md
|-- DEBUG.md
|-- DEBUG.archive.md
|-- pyproject.toml
|-- scripts/
|-- src/tradecat_terminal/
`-- tests/
```

## Mission

TradeCat public reads public Google Sheets CSV endpoints, writes local JSON snapshot cache files, and exposes CLI/TUI/export flows for users and agents.

## Forbidden Paths

- No TradeCat server PostgreSQL access.
- No SQLite or SQL query layer.
- No server production-chain dependency.
- No private credentials or generated cache files in Git.
- No root `assets/` or `assets/examples/`.

## Movement Rules

- Keep `.git/`, `.github/`, `.gitignore`, `SKILL.md`, `agents/`, `references/`, and root thin validation/helper scripts in the Skill root.
- Keep Python project files, installers, project README, project scripts, `src/`, and `tests/` in `scripts/project/`.
- Keep root/project `AGENTS.md` and project `DEBUG*.md` tracked as public governance and debugging memory.
- Never put credentials, generated cache data, private `.env` values, or machine-local runtime state into tracked governance/debug files.
- When the layout changes, update `README.md`, `SKILL.md`, `references/index.md`, this file, `references/linear-flows.md` when flow behavior changes, and the tracked `AGENTS.md` copies.

## Main Flow

```text
Public Google Sheets CSV
-> dataset_registry.json
-> sheets.py fetch/parse
-> cache.py snapshot or stream merge
-> structured_cache.py latest.json/latest.jsonl/latest.csv/manifest.json
-> cli.py, tui.py, view_model.py
```

## Source Boundaries

- `registry.py`: dataset/workbook/gid/data mode single source of truth.
- `cache.py`: local snapshot cache, manifest, stream event merge, prune.
- `structured_cache.py`: structured latest projections.
- `view_model.py`: display/raw/physical column model.
- `tui.py`: cache-first terminal browser and background probes.
- `scripts/project/scripts/request.py`: zero-install standard-library public request entry.
- `scripts/bootstrap-dev.sh`: root developer bootstrap wrapper for `scripts/project/.venv`.
- `scripts/security-scan.sh`: root secret-scan wrapper; scans tracked files by default and commit ranges in CI.

## Documentation Map

- `README.md`: root boundary map for the Skill wrapper, Git metadata, and bundled project location.
- `AGENTS.md`: tracked root operating contract for directory governance and movement rules.
- `SKILL.md`: skill activation, root-level operating commands, and high-level boundaries.
- `references/*.md`: long-form skill references loaded on demand.
- `references/linear-flows.md`: public linear flow map for cache, TUI, request, install, uninstall, and export/config paths.
- `references/quality-gate.md`: validation, root audit, and release evidence checklist.
- `scripts/project/README.md`: user-facing install, run, request, config, and development instructions.
- `scripts/project/AGENTS.md`: tracked project engineering contract and linear flows.
- `scripts/project/DEBUG.md`: tracked current truth and recent debugging notes.
- `scripts/project/DEBUG.archive.md`: tracked historical accident record.

Root/project `AGENTS.md` and project `DEBUG*.md` are intentionally tracked. Keep them concise, public-safe, and aligned with `README.md`, `SKILL.md`, and `references/`.
