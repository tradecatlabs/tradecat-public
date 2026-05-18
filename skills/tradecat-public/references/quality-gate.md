# Quality Gate

## Mandatory Gate

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
python3 scripts/validate_dependency_policy.py
ruff format --check src tests scripts
git diff --check
```

## Boundary Audit

- Root is the Python project root.
- Skill package is only `skills/tradecat-public/`.
- No root `SKILL.md`, `agents/`, or `references/`.
- No tracked `project/` or `tasks/`.
- No `src/tradecat_terminal/`.
- No root install/uninstall scripts.
- No old `scripts/start.sh` or `scripts/watchdog.sh`.
- No tracked `.runtime/`, `.tradecat/`, `.venv/`, `.hermes/`, `.tools/`, credentials, caches, paper ledgers, or audit journals.
- `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE`, `.github/pull_request_template.md`, `.github/CODEOWNERS`, `.github/dependabot.yml`, `.editorconfig`, `.env.example`, and `docs/` stay present as repository governance entrypoints.

Use:

```bash
bash scripts/guard_public_local_files.sh
```

## Agent Contract Audit

- `skills/tradecat-public/agents/manifest.json` parses with `python3 -m json.tool`.
- Every advertised schema file exists under `contracts/`.
- Safety fields remain false for `real_orders`, `signed_requests`, and `reads_api_keys`.
- Binance resources remain self-contained under `resources/agent_market_context/binance/`.
- Docs reference manifest as the only machine contract.
- CI and local verify run lint, format check, dependency policy, tests, schema validators, secret scan, and supply-chain audit.

## Runtime Safety Audit

- `context-audit` runs before `run-context`.
- Missing Agent sizing/exits returns structured reject.
- Paper runtime writes only ignored `.runtime/auto-paper/`.
- `paper-report`, `health-report`, `daily-report`, `audit-journal`, and `replay-report` do not create or require Binance credentials.

## Delivery Evidence

Final delivery should report changed files, validation commands, failures if any, commit SHA if a checkpoint commit was requested or created, current git status, and remaining blockers.
