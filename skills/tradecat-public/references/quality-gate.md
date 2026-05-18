# Quality Gate

Use this checklist before delivering changes to the repository-root TradeCat
public project or its embedded Skill package.

## Skill Gate

Run the strict validator from the repository root:

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

Run project verification from the repository root:

```bash
bash scripts/bootstrap-dev.sh
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
```

Acceptance:

- `scripts/guard_public_local_files.sh` passes.
- Python source and tests compile.
- `pytest` passes.
- Root project verification bootstraps `.venv` when `pytest` or
  `ruff` is missing on a bare checkout, then runs `ruff` from the bootstrapped
  environment.
- Shell syntax checks pass.
- `scripts/request.py` compiles.
- Project verification removes generated `__pycache__`, `.pytest_cache`, and
  `.ruff_cache` directories before exit.
- CI runs a Gitleaks secret scan before project install/test steps.
- `scripts/security-scan.sh` scans tracked files only by default, excluding
  ignored runtime directories such as `.venv/` and `.tradecat/`.
- `scripts/security-scan.sh` uses a digest-pinned Gitleaks container when Docker
  is needed, and can bootstrap a local Gitleaks binary when Docker is absent.
- `scripts/supply-chain-audit.sh` audits the Python project with pinned
  `pip-audit`.
- Python dependency installation uses `constraints.txt` for
  local bootstrap, CI install, and user installer paths.
- CI uploads dependency freeze/constraints evidence for release audit.
- `scripts/validate_data_contract.py --remote` validates the
  public Google Sheets CSV shape for active datasets in CI.
- `scripts/validate_dataset_consumption_contract.py` validates
  the machine-readable dataset field semantics, missing-value policy, time
  grain, and quality tier against `dataset_registry.json`.
- `scripts/agent-smoke.sh` validates `skills/tradecat-public/agents/manifest.json`, advertised JSON
  schemas, non-zero failure exit codes, the zero-install request fallback, and
  the split between `invalid_dataset_key` and `invalid_runtime_configuration`.
- `scripts/agent-smoke.sh` also covers `doctor --json`, `config show --json`,
  dry-run `prune --json`, single-dataset `probe --json --no-write`, and
  all-dataset `probe --json --no-write`, plus `features --json` empty-cache
  error semantics.
- Watcher lifecycle control has a machine-readable JSON contract through
  `scripts/start.sh status/start/stop --json`,
  `scripts/watchdog.sh --json`, and
  `tradecat.watch_status.v1`.
- CI has an independent `agent-readiness` job so Agent contract drift fails even
  when ordinary human-facing docs still look valid.
- Advertised JSON commands include `schema` and `schema_version`; failed JSON
  commands include an object `error` with `code`, `kind`, `message`, `hint`, and
  `retryable`.
- Formal JSON Schema drafts under `contracts/*.schema.json` stay
  valid JSON and match the advertised manifest/envelope/error/command contract.
- Every schema advertised in `agents/manifest.json` has exactly one
  command-level schema file, and CLI-only internal schemas remain explicitly
  allowlisted in `tests/test_agent_contract.py`.
- `tests/test_payload_schema_validation.py` validates real
  CLI/request JSON payloads and golden fixtures against those formal schemas;
  `jsonschema` remains a dev/test dependency, not a runtime dependency.
- `tradecat datasets --json` exposes `consumption_contract` for every dataset,
  so Agents can consume dataset semantics without reading long-form docs first.
- `tradecat analyze --json` exposes `tradecat.analysis_report.v1` as a local
  readonly observation report, validates against its formal schema, and returns
  `empty_analysis_cache` instead of free-form text when the cache has no
  analyzable rows.
- `tradecat features --json` exposes `tradecat.feature_bundle.v1` as a local
  readonly per-symbol fact bundle, validates against its formal schema, and
  returns `empty_feature_cache` instead of free-form text when the cache has no
  symbol candidates.
- Published raw installer smoke does not set `TRADECAT_INSTALL_SKIP_SYNC` and
  fails if the default `event_stream` cache is still not ready after install and
  explicit `doctor --sync` repair.
- Published raw installer smoke uses limited retry and uploads status/support
  bundle artifacts; scheduled/manual runs are canaries, push/PR gates remain
  deterministic except for the explicitly live public data checks.
- Python 3.12 and 3.13 must pass the main verify job; cross-platform smoke covers
  Unix shell, PowerShell, status JSON, and plain TUI.
- QA strategy and regression scope are maintained in
  `references/test-strategy.md`; new high-risk behavior should either map to an
  existing listed gate or extend that reference and the matching tests.

## Root Boundary Gate

Run these checks after any layout or documentation movement:

```bash
bash scripts/guard_public_local_files.sh
```

Acceptance:

- No root `SKILL.md`, `agents/`, or `references/`; those live only under
  `skills/tradecat-public/`.
- Root `src/`, `tests/`, `contracts/`, `resources/`, `pyproject.toml`,
  `Makefile`, install scripts, uninstall scripts, and project scripts remain at
  the repository root.
- `.git/`, `.github/`, `.gitignore`, `.pre-commit-config.yaml`, and root scripts
  such as `scripts/verify.sh`, `scripts/security-scan.sh`,
  `scripts/supply-chain-audit.sh`, `scripts/agent-smoke.sh`, and
  `scripts/run-tradecat.sh` remain at root.
- `skills/tradecat-public/scripts/` contains only thin wrappers back to root
  project scripts.
- Root `AGENTS.md` and `DEBUG*.md` are tracked public governance
  files and contain no secrets, cache payloads, or private environment values.

## Documentation Gate

When a layout, entrypoint, data flow, cache contract, TUI contract, installer, or
quality rule changes, update the matching documentation in the same change:

- Root movement or Skill behavior: `README.md`, `skills/tradecat-public/SKILL.md`,
  `skills/tradecat-public/references/index.md`, `skills/tradecat-public/references/architecture.md`.
- Agent machine contract behavior: `skills/tradecat-public/agents/manifest.json`, `skills/tradecat-public/agents/*.yaml`,
  `skills/tradecat-public/references/agent-contract.md`, `skills/tradecat-public/references/quality-gate.md`.
- Analysis report behavior: `references/analysis-contract.md`.
- Feature bundle behavior: `references/feature-contract.md`.
- Test strategy or release QA scope: `references/test-strategy.md`.
- Public flow behavior: `references/linear-flows.md`.
- Cache behavior: `references/cache-contract.md`.
- TUI behavior: `references/tui-contract.md`.
- First-run cache behavior: `references/first-run-cache.md`.
- Installer or uninstall behavior: `references/install-uninstall.md`.
- Quality requirements: `references/quality-gate.md`.
- Release evidence: `references/release.md`.
- Governance/debug memory: root `AGENTS.md`, root `lessons.md`, and root `DEBUG*.md`.

## Git Evidence

Before commit or handoff:

```bash
git diff --check
bash scripts/agent-smoke.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git status --short --branch --ignored
```

Acceptance:

- Public changes are staged intentionally.
- Ignored runtime files such as `.venv/` and `.tradecat/` stay untracked.
- Tracked governance/debug files such as `AGENTS.md` and `DEBUG*.md`
  are reviewed for public-safe content before commit.
- No generated cache, credentials, private `.env`, or runtime state enters Git.
- Secret scanning passes locally when available and in GitHub Actions.
- `bash scripts/clean-local-runtime.sh --apply` may be used at the end of local
  work to remove ignored runtime directories from the working tree.
