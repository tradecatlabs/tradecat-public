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
-> Node 3: `sheets.py` fetches read-only CSV and parses it into a matrix
-> Node 4: `cache.py` writes a snapshot file only when the full matrix hash changes
-> Node 5: `cache.py` merges `event_stream` by event_key and normalized_event_key into `stream_events.json`
-> Node 6: `structured_cache.py` writes `latest.json`, `latest.jsonl`, `latest.csv`, and root manifest
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
-> Output: table, json, jsonl, csv, raw, or metadata output on stdout with no local writes
```

## Flow 4: User Install

```text
Input: `curl .../scripts/project/install.sh | sh` or `irm .../scripts/project/install.ps1 | iex`
-> Node 1: installer parses install dir, bin dir, repository, branch/ref, project subdir, and Python version environment variables
-> Node 2: installer clones or updates the configured repository branch, or checks out a fixed `TRADECAT_INSTALL_REF`
-> Node 3: installer prefers local Python 3.12 and falls back to uv-managed Python 3.12 when needed
-> Node 4: installer locates `scripts/project/`, creates `.venv`, and performs editable install
-> Node 5: installer writes `tradecat` and `tcat` launchers with throttled background update and force-update support; pinned ref installs skip auto-update
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
-> Node 2: `settings.py` reads or writes local `.tradecat/settings.json` user preferences
-> Node 3: `view_model.py` constructs the display model from local cache while preserving display/raw/physical fields
-> Node 4: `cli.py` writes json, jsonl, csv, or table output; jsonl/csv preserve raw fields and table preserves physical A/B/C columns
-> Output: local configuration state or local cached view export for users, shell scripts, and agents
```
