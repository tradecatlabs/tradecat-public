# Architecture

`tradecat-public` is a Codex skill wrapper around a bundled user-side TradeCat project.

The project itself lives in `scripts/project/` and keeps its original Python package shape:

```text
scripts/project/
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

## Documentation Map

- `README.md`: root boundary map for the Skill wrapper, Git metadata, and bundled project location.
- `AGENTS.md`: local-only root operating contract for directory governance and movement rules.
- `SKILL.md`: skill activation, root-level operating commands, and high-level boundaries.
- `references/*.md`: long-form skill references loaded on demand.
- `scripts/project/README.md`: user-facing install, run, request, config, and development instructions.
- `scripts/project/AGENTS.md`: local-only project engineering contract and linear flows.
- `scripts/project/DEBUG.md`: local-only current truth and recent debugging notes.
- `scripts/project/DEBUG.archive.md`: local-only historical accident record.

Root/project `AGENTS.md` and project `DEBUG*.md` are intentionally local-only and ignored by Git; public, reusable guidance belongs in `README.md`, `SKILL.md`, and `references/`.
