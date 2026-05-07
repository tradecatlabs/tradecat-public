# Quality Gate

Use this checklist before delivering changes to the Skill wrapper or the bundled
TradeCat public project.

## Skill Gate

Run the strict validator from the Skill root:

```bash
bash scripts/validate-skill.sh --strict
```

Acceptance:

- `SKILL.md` frontmatter name is `tradecat-public`.
- `description` states capability and concrete activation triggers.
- `When to Use This Skill`, `Not For / Boundaries`, `Quick Reference`,
  `Examples`, `References`, and `Maintenance` remain present.
- Quick Reference stays operator-focused and below 20 patterns.
- Long explanations live under `references/`.

## Project Gate

Run project verification from the Skill root:

```bash
bash scripts/verify.sh
```

Acceptance:

- `scripts/project/scripts/guard_public_local_files.sh` passes.
- Python source and tests compile.
- `pytest` passes.
- `ruff` runs when installed; if it is unavailable locally, the script prints
  the local limitation and CI remains the definitive lint gate.
- Shell syntax checks pass.
- `scripts/project/scripts/request.py` compiles.
- Project verification removes generated `__pycache__`, `.pytest_cache`, and
  `.ruff_cache` directories before exit.

## Root Boundary Gate

Run these checks after any layout or documentation movement:

```bash
bash scripts/project/scripts/guard_public_local_files.sh
```

Acceptance:

- No root `assets/` or `assets/examples/`.
- No root `src/`, `tests/`, `pyproject.toml`, `Makefile`, install script, or
  uninstall script.
- `.git/`, `.github/`, `.gitignore`, `SKILL.md`, `agents/`, `references/`,
  `scripts/verify.sh`, and `scripts/run-tradecat.sh` remain at root.
- Project source, tests, installers, project README, and project scripts remain
  under `scripts/project/`.
- Root/project `AGENTS.md` and project `DEBUG*.md` are tracked public governance
  files and contain no secrets, cache payloads, or private environment values.

## Documentation Gate

When a layout, entrypoint, data flow, cache contract, TUI contract, installer, or
quality rule changes, update the matching documentation in the same change:

- Root movement or Skill behavior: `README.md`, `SKILL.md`,
  `references/index.md`, `references/architecture.md`.
- Public flow behavior: `references/linear-flows.md`.
- Cache behavior: `references/cache-contract.md`.
- TUI behavior: `references/tui-contract.md`.
- Installer or uninstall behavior: `references/install-uninstall.md`.
- Quality requirements: `references/quality-gate.md`.
- Governance/debug memory: root/project `AGENTS.md` and project `DEBUG*.md`.

## Git Evidence

Before commit or handoff:

```bash
git diff --check
git status --short --branch --ignored
```

Acceptance:

- Public changes are staged intentionally.
- Ignored runtime files such as `.venv/` and `.tradecat/` stay untracked.
- Tracked governance/debug files such as `AGENTS.md` and project `DEBUG*.md`
  are reviewed for public-safe content before commit.
- No generated cache, credentials, private `.env`, or runtime state enters Git.
