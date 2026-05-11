# Linear Flows

These flows are the public, reusable version of the project operating map. Each
node must trace back to code, scripts, configuration, data, or documentation.

## Flow Rules

- Nodes must cover the real main path exactly.
- Do not add fictional orchestration nodes.
- Do not omit required runtime steps.
- Update this file when architecture, entrypoints, data flow, or control flow changes.

## Flow 1: Public Sheets To Local Snapshot Cache

```text
Input: public Google Sheets CSV, dataset registry, local cache_dir
-> Node 1: `cli.py` / `lifecycle.py` receives sync, probe, or watch commands and resolves cache_dir
-> Node 2: `registry.py` loads workbook, tab, gid, dataset_key, and data_mode from `dataset_registry.json`
-> Node 3: `dataset_contract.py` exposes dataset consumption semantics from `dataset_consumption_contract.json`
-> Node 4: `sheets.py` fetches read-only CSV with bounded retry/backoff/jitter and typed remote errors
-> Node 5: `migrations.py` checks cache metadata schema and backs up before local migration when needed
-> Node 6: `cache.py` writes a snapshot file under `state.py` locks only when the full matrix hash changes
-> Node 7: `cache.py` merges `event_stream` by event_key and normalized_event_key into `stream_events.json`
-> Node 8: `structured_cache.py` writes `latest.json`, `latest.jsonl`, `latest.csv`, and root manifest atomically
-> Output: local structured snapshot cache for TUI, CLI export, request consumers, and agents
```

## Flow 2: Local Cache To TUI Display

```text
Input: TUI request, cache_dir, dataset registry, language option or `TRADECAT_LANG`
-> Node 1: `cli.py` / `tui.py` parses TUI arguments, cache_dir, and language
-> Node 2: `settings.py` supplies default language, default tap, cache_dir, and probe interval settings
-> Node 3: `tui.py` starts cache-first and does not block startup on remote CSV fetch
-> Node 4: `cache.py` separates metadata, links, business header, business rows, physical columns, and raw fields
-> Node 5: `view_model.py` builds physical A/B/C display columns and raw/display/physical column metadata
-> Node 6: `tui.py` renders a real-content-width psql table without frozen columns or right-side horizontal table scrolling
-> Node 7: `tui.py` handles help, status, search, navigation, selection, URL opening, and symbol links
-> Node 8: `tui.py` runs live probe in background for the focused dataset and refreshes active non-focused datasets on their intervals
-> Node 9: remote changes update structured cache and invalidate only the affected dataset view/render caches
-> Output: terminal browser over local JSON cache without SQL or server database dependency
```

## Flow 3: Zero-install One-shot Request

```text
Input: `python3 <(curl .../scripts/project/scripts/request.py) <dataset_key>`, public registry JSON, public Google Sheets CSV
-> Node 1: `scripts/project/scripts/request.py` reads registry URL and parses format, limit, meta, and headers arguments
-> Node 2: `scripts/project/scripts/request.py` builds a Google Sheets CSV export URL from the shared registry
-> Node 3: `scripts/project/scripts/request.py` fetches CSV, parses top information rows, headers, and business rows without third-party packages
-> Node 4: JSON mode wraps success or failure in `tradecat.request_result.v1` with `schema_version` and stable `error`
-> Output: table, json, jsonl, csv, raw, or metadata output on stdout with no local writes
```

## Flow 4: User Install

```text
Input: `curl .../scripts/project/install.sh | sh` or `irm .../scripts/project/install.ps1 | iex`
-> Node 1: installer parses install dir, bin dir, repository, branch/ref, project subdir, and Python version environment variables
-> Node 2: installer checks out the stable default ref, or clones/updates a configured branch only when `TRADECAT_INSTALL_BRANCH` is explicit
-> Node 3: installer prefers local Python 3.12, then existing uv; remote uv bootstrap requires `TRADECAT_INSTALL_ALLOW_UV_BOOTSTRAP=1`
-> Node 4: installer locates `scripts/project/`, creates `.venv`, and performs editable install through `constraints.txt`
-> Node 5: installer writes `tradecat` and `tcat` launchers; stable/pinned installs skip auto-update, while explicit branch-channel installs use throttled background update and force-update support
-> Node 6: installer writes `tradecat-uninstall` and `tcat-uninstall` launchers
-> Node 7: installer runs `tradecat init` with `TRADECAT_NO_AUTO_UPDATE=1`, best-effort `tradecat sync-all` unless skipped, and falls back to `tradecat sync event_stream` if the full sync fails
-> Output: user can run `tradecat`, `tcat`, `tradecat-uninstall`, and `tcat-uninstall` from the configured bin dir
```

## Flow 5: User Uninstall

```text
Input: `tradecat-uninstall`, `curl .../scripts/project/uninstall.sh | sh`, or `irm .../scripts/project/uninstall.ps1 | iex`
-> Node 1: uninstaller parses install dir, bin dir, runtime dir, project subdir, and `TRADECAT_KEEP_CACHE`
-> Node 2: if `TRADECAT_KEEP_CACHE=1`, uninstaller preserves `scripts/project/.tradecat/cache` with legacy root cache fallback
-> Node 3: uninstaller removes `tradecat`, `tcat`, `tradecat-uninstall`, and `tcat-uninstall` command entries
-> Node 4: uninstaller removes the TradeCat install directory and watch runtime directory
-> Output: TradeCat is removed; system Python, Git, uv, and user PATH remain untouched
```

## Flow 6: Local Config And View Export

```text
Input: `tradecat config ...` or `tradecat export <dataset_key>`
-> Node 1: `cli.py` parses config/export command, cache_dir, output format, and language
-> Node 2: `settings.py` reads or writes local `.tradecat/settings.json` user preferences using lock, atomic replace, `.bak`, and corrupt backup
-> Node 3: `view_model.py` constructs the display model from local cache while preserving display/raw/physical fields
-> Node 4: `cli.py` writes json, jsonl, csv, or table output; jsonl/csv preserve raw fields and table preserves physical A/B/C columns
-> Output: local configuration state or local cached view export for users, shell scripts, and agents
```

## Flow 7: Doctor Diagnostics And Repair

```text
Input: `tradecat doctor`, `tradecat doctor --repair`, `tradecat doctor --verbose`, or `tradecat doctor --bundle`
-> Node 1: `cli.py` parses local-only repair, explicit sync, verbose, and bundle flags
-> Node 2: `lifecycle.py` builds cache status, settings health, migration status, recent errors, and disk-waterline diagnostics
-> Node 3: `migrations.py` runs only when `--repair` is explicit and backs up metadata before rewrite
-> Node 4: `diagnostics.py` emits public-safe support bundle JSON without cache row payloads or secrets
-> Output: actionable local health report, repair hints, optional metadata migration, and optional support bundle
```

## Flow 8: Local Analysis Report

```text
Input: `tradecat analyze --json`, local cache, dataset consumption contract
-> Node 1: `cli.py` parses window and candidate limit without triggering network fetch
-> Node 2: `analysis.py` reads the latest local views for `event_stream`, `anomaly_panel`, and `market_stats`
-> Node 3: `dataset_contract.py` supplies field roles, time grain, missing-value policy, and quality tier
-> Node 4: `analysis.py` emits observations, candidate symbols from explicit entity fields, row evidence, risk flags, and limitations
-> Node 5: `contracts.py` wraps the payload as `tradecat.analysis_report.v1` or returns `empty_analysis_cache`
-> Output: Agent-readable observation report with no strategy, advice, backtest, network, or cache-write side effect
```

## Flow 9: Agent Fast Path

```text
Input: shell-capable Agent or Hermes session at repository root
-> Node 1: Agent reads `agents/manifest.json` as the canonical machine contract
-> Node 2: Agent runs `bash scripts/run-tradecat.sh status --json` and trusts `schema=tradecat.status.v1`
-> Node 3: Agent runs `bash scripts/run-tradecat.sh datasets --json` and reads each dataset `consumption_contract`
-> Node 4: Agent runs `bash scripts/run-tradecat.sh path <dataset_key> --json` to locate local cache artifacts
-> Node 5: Agent runs `bash scripts/run-tradecat.sh analyze --json` when local cache is already populated and an observation report is needed
-> Node 6: Agent uses `scripts/project/scripts/request.py <dataset_key> --format json` for network-readonly public data, or explicit `sync` only when cache writes are required
-> Node 7: Agent runs `bash scripts/agent-smoke.sh` before delivery to validate manifest, JSON schema, exit-code, dataset consumption, and analysis contracts
-> Output: inspect -> validate -> consume -> diagnose flow with no guessing and no accidental install/uninstall side effects
```
