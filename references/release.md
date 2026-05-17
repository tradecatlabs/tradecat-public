# Release Notes

## v0.1.3

Release date: 2026-05-10.

Commit: `v0.1.3` tag target.

GitHub Release: <https://github.com/tukuaiai/tradecat/releases/tag/v0.1.3>.

CI evidence:

- Develop workflow query: <https://github.com/tukuaiai/tradecat/actions/workflows/ci.yml?query=branch%3Adevelop+event%3Apush>
- Tag workflow query: <https://github.com/tukuaiai/tradecat/actions/workflows/ci.yml?query=branch%3Av0.1.3>

Install:

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.3/project/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.3/project/install.ps1 | iex
```

Highlights:

- Makes stable `v0.1.3` the default install ref for ordinary users.
- Promotes Agent contract hardening from `develop` into the stable channel:
  manifest/schema 1:1 coverage, real payload schema validation, golden JSON
  fixtures, and expanded `agent-smoke`.
- Adds the formal `tradecat.watch_status.v1` watcher lifecycle contract for
  `project/scripts/start.sh --json` status/start/stop output.
- Keeps `tradecat.watch_cycle.v1` internal until the long-running watch stream
  is intentionally promoted.
- Updates GitHub artifact upload actions to the Node 24-compatible major.
- Clarifies Agent dry-run probe usage and local dev bootstrap requirements.

Known limits:

- Public data still depends on public Google Sheets CSV availability.
- Stable tag installs intentionally do not auto-update.
- `tradecat.watch_cycle.v1` remains an internal long-running stream payload,
  not a formal Agent surface.

Rollback:

```bash
tradecat-uninstall
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.2/project/install.sh | TRADECAT_INSTALL_REF=v0.1.2 sh
```

## v0.1.2

Release date: 2026-05-08.

Commit: `v0.1.2` tag target.

GitHub Release: <https://github.com/tukuaiai/tradecat/releases/tag/v0.1.2>.

CI evidence:

- Develop workflow query: <https://github.com/tukuaiai/tradecat/actions/workflows/ci.yml?query=branch%3Adevelop+event%3Apush>
- Tag workflow query: <https://github.com/tukuaiai/tradecat/actions/workflows/ci.yml?query=branch%3Av0.1.2>

Release evidence rule:

- Tag-bound release notes use stable tag/workflow URLs instead of post-tag run
  IDs. Exact GitHub Actions run IDs belong in the GitHub Release body and final
  delivery report, so a release tag never needs mutation after publication.

Install:

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.2/project/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.2/project/install.ps1 | iex
```

Highlights:

- Makes stable `v0.1.2` the default install ref for ordinary users.
- Aligns Python package metadata and runtime `__version__` with `0.1.2`.
- Keeps `TRADECAT_INSTALL_BRANCH=develop` as the explicit auto-update channel.
- Makes published raw installer CI perform real initial sync and assert that
  `event_stream` is ready after install or explicit repair.
- Allows root/project verify scripts to bootstrap missing dev tooling instead
  of failing on a bare checkout.

Known limits:

- Public data still depends on public Google Sheets CSV availability.
- Branch-channel installs auto-update; stable tag installs intentionally do not.

Rollback:

```bash
tradecat-uninstall
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.1/project/install.sh | TRADECAT_INSTALL_REF=v0.1.1 sh
```

## Next Long-Running Contract Work

Target: next tag after `v0.1.3`.

Candidates:

- Decide whether `tradecat.watch_cycle.v1` should remain an internal stream
  payload or become a formal Agent surface.
- If promoted, add manifest/schema/live payload tests and a bounded
  `watch --json --max-cycles 1 --no-write` smoke.
- Keep `start.sh --json` as the watcher lifecycle control plane and avoid
  treating process spawn as proof of remote data health.

Release gate before tagging:

```bash
bash scripts/validate-skill.sh --strict
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
```

## v0.1.1

Release date: 2026-05-08.

Commit: `7626d3a8e6f1a5b525d523b2fc9395f1294f7deb`.

GitHub Release: <https://github.com/tukuaiai/tradecat/releases/tag/v0.1.1>.

CI evidence:

- Develop CI: <https://github.com/tukuaiai/tradecat/actions/runs/25531835777>
- Tag CI: <https://github.com/tukuaiai/tradecat/actions/runs/25531835774>

Install:

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.1/project/install.sh | TRADECAT_INSTALL_REF=v0.1.1 sh
```

Windows PowerShell:

```powershell
$env:TRADECAT_INSTALL_REF = "v0.1.1"; irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.1/project/install.ps1 | iex
```

Highlights:

- Replaces stale launcher symlinks instead of following broken symlink targets.
- Hardens first-run cache behavior with `event_stream` installer fallback.
- Adds cold-start diagnostics for empty-cache TUI states.
- Adds explicit sync timeout controls and `tradecat doctor --sync`.

Known limits:

- Public data still depends on public Google Sheets CSV availability.
- Fixed ref installs intentionally skip launcher auto-update.

Rollback:

```bash
tradecat-uninstall
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/project/install.sh | TRADECAT_INSTALL_REF=v0.1.0 sh
```

## v0.1.0

Release date: 2026-05-07.

Commit: `2b5a1af96efd0e95a2524afbbc67708886b6f890`.

GitHub Release: <https://github.com/tukuaiai/tradecat/releases/tag/v0.1.0>.

CI evidence:

- Develop CI: <https://github.com/tukuaiai/tradecat/actions/runs/25471829267>
- Tag CI: <https://github.com/tukuaiai/tradecat/actions/runs/25471890550>

Install:

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/project/install.sh | TRADECAT_INSTALL_REF=v0.1.0 sh
```

Windows PowerShell:

```powershell
$env:TRADECAT_INSTALL_REF = "v0.1.0"; irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/project/install.ps1 | iex
```

Highlights:

- Standard Skill wrapper with all project source under `project/`.
- Cache-first CLI/TUI backed by local JSON snapshot cache files.
- POSIX and PowerShell installers with pinned ref install support.
- Skill strict validation, root boundary guard, secret scan, tests, wheel data
  checks, and cross-platform smoke tests.

Known limits:

- Public data comes from public Google Sheets CSV endpoints; remote availability
  is outside this repository.
- Fixed ref installs intentionally skip launcher auto-update.
- User runtime directories and cache files are local state and are not tracked.

Rollback:

```bash
tradecat-uninstall
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/project/install.sh | TRADECAT_INSTALL_REF=v0.1.0 sh
```

For Windows, rerun the fixed-ref PowerShell installer above after
`tradecat-uninstall`.
