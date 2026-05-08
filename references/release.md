# Release Notes

## v0.1.1

Release date: 2026-05-08.

Commit: `7626d3a8e6f1a5b525d523b2fc9395f1294f7deb`.

GitHub Release: <https://github.com/tukuaiai/tradecat/releases/tag/v0.1.1>.

CI evidence:

- Develop CI: <https://github.com/tukuaiai/tradecat/actions/runs/25531835777>
- Tag CI: <https://github.com/tukuaiai/tradecat/actions/runs/25531835774>

Install:

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.1/scripts/project/install.sh | TRADECAT_INSTALL_REF=v0.1.1 sh
```

Windows PowerShell:

```powershell
$env:TRADECAT_INSTALL_REF = "v0.1.1"; irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.1/scripts/project/install.ps1 | iex
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
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/scripts/project/install.sh | TRADECAT_INSTALL_REF=v0.1.0 sh
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
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/scripts/project/install.sh | TRADECAT_INSTALL_REF=v0.1.0 sh
```

Windows PowerShell:

```powershell
$env:TRADECAT_INSTALL_REF = "v0.1.0"; irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/scripts/project/install.ps1 | iex
```

Highlights:

- Standard Skill wrapper with all project source under `scripts/project/`.
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
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.0/scripts/project/install.sh | TRADECAT_INSTALL_REF=v0.1.0 sh
```

For Windows, rerun the fixed-ref PowerShell installer above after
`tradecat-uninstall`.
