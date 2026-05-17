# Install And Uninstall

The bundled project keeps installer logic in `project/install.sh` and `project/install.ps1`.

## Install

- By default, install the stable `TRADECAT_INSTALL_DEFAULT_REF` tag, currently
  `v0.1.3`.
- Clone or update a configured branch only when `TRADECAT_INSTALL_BRANCH` is
  explicitly set, or checkout a fixed `TRADECAT_INSTALL_REF` tag/ref.
- Locate the project inside the repository by `TRADECAT_PROJECT_SUBDIR`, defaulting to `project`.
- Use Python 3.12 when available.
- Fall back to an existing `uv` for Python 3.12 environment creation when needed.
- If neither Python 3.12+ nor `uv` exists, fail with a clear supply-chain
  message unless the user explicitly sets `TRADECAT_INSTALL_ALLOW_UV_BOOTSTRAP=1`.
- Install the bundled project from `project`; when `constraints.txt`
  exists, POSIX and PowerShell installers must pass that constraints file to
  `pip` / `uv pip`.
- Write `tradecat`, `tcat`, `tradecat-uninstall`, and `tcat-uninstall` launchers.
- Existing launcher files or stale symlinks under `TRADECAT_BIN_DIR` are replaced
  in place; installer must not follow old symlink targets.
- Run `tradecat init` with `TRADECAT_NO_AUTO_UPDATE=1`.
- Run initial `tradecat sync-all` best-effort unless skipped.
- If initial `sync-all` fails, fall back to `tradecat sync event_stream`
  so the default no-argument TUI has a useful first cache whenever the default
  dataset can be fetched.
- CI validates both local checkout installers and published
  `raw.githubusercontent.com/.../v0.1.3/...` installers. Published installer
  smoke must not set `TRADECAT_INSTALL_SKIP_SYNC`; it must assert that
  `event_stream` is ready after install or explicit `doctor --sync` repair.
- Published installer smoke keeps retry logs, status JSON, and support bundle
  artifacts so live Google Sheets/network failures can be diagnosed separately
  from code regressions.

## Launcher Auto-update

- Auto-update belongs to launcher scripts, not imported Python modules.
- Stable default installs and installs pinned with `TRADECAT_INSTALL_REF` do not auto-update.
- Branch-channel installs created with `TRADECAT_INSTALL_BRANCH=develop` auto-update.
- `TRADECAT_NO_AUTO_UPDATE=1` skips update.
- `TRADECAT_FORCE_UPDATE=1` blocks startup until update succeeds; failure exits.
- Normal update is throttled by `TRADECAT_UPDATE_INTERVAL_SECONDS` and runs in background.
- `TRADECAT_INSTALL_ALLOW_UV_BOOTSTRAP=1` is the only supported path that lets
  the installer execute the remote uv bootstrap script.

## Uninstall

- Remove TradeCat install directory, launcher files, and local watch runtime.
- Do not remove system Python, Git, uv, or user PATH.
- `TRADECAT_KEEP_CACHE=1` preserves `project/.tradecat/cache` before deleting the install directory, with legacy root cache as a fallback.
