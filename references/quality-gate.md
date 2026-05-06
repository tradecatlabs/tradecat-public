# Quality Gate

Use this checklist before delivering changes to the Skill wrapper or the bundled
TradeCat public project.

## Skill Gate

Run the strict validator from the parent directory so the directory name matches
the frontmatter name:

```bash
cd ..
bash /home/lenovo/.codex/skills/auto-skill/scripts/validate-skill.sh tradecat-public --strict
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
- Shell syntax checks pass.
- `scripts/project/scripts/request.py` compiles.

If `ruff` is available, also run:

```bash
cd scripts/project
ruff check src tests
```

## Root Boundary Gate

Run these checks after any layout or documentation movement:

```bash
test ! -e assets
git ls-files | sort
git check-ignore -v AGENTS.md scripts/project/AGENTS.md scripts/project/DEBUG.md scripts/project/DEBUG.archive.md || true
```

Acceptance:

- No root `assets/` or `assets/examples/`.
- No root `src/`, `tests/`, `pyproject.toml`, `Makefile`, install script, or
  uninstall script.
- `.git/`, `.github/`, `.gitignore`, `SKILL.md`, `agents/`, `references/`,
  `scripts/verify.sh`, and `scripts/run-tradecat.sh` remain at root.
- Project source, tests, installers, project README, and project scripts remain
  under `scripts/project/`.
- Local-only `AGENTS.md` and `DEBUG*.md` files are ignored by Git.

## Documentation Gate

When a layout, entrypoint, data flow, cache contract, TUI contract, installer, or
quality rule changes, update the matching documentation in the same change:

- Root movement or Skill behavior: `README.md`, `SKILL.md`,
  `references/index.md`, `references/architecture.md`.
- Cache behavior: `references/cache-contract.md`.
- TUI behavior: `references/tui-contract.md`.
- Installer or uninstall behavior: `references/install-uninstall.md`.
- Quality requirements: `references/quality-gate.md`.
- Local operating memory: root/project `AGENTS.md` when present.

## Git Evidence

Before commit or handoff:

```bash
git diff --check
git status --short --branch --ignored
```

Acceptance:

- Public changes are staged intentionally.
- Ignored runtime files such as `.venv/`, `.tradecat/`, local `AGENTS.md`, and
  project `DEBUG*.md` stay untracked.
- No generated cache, credentials, private `.env`, or runtime state enters Git.
