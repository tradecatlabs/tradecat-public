# First-run Cache Runbook

TradeCat 的默认用户体验是 `tradecat` 直接打开 `signal_flow`。因此首次缓存不是内部实现细节，而是用户入口契约。

## Failure Shape

- `cache=empty-cache` means the selected dataset has no `latest.json`.
- `remote=-` and `fetched=-` mean no successful local snapshot exists yet.
- `probe=probing` means TUI has started a background fetch.
- `fail=N` after timeout means the background fetch failed, but the TUI process itself is still alive.

## Prevention Rules

- Installer must run `tradecat init` and best-effort `tradecat sync-all` unless `TRADECAT_INSTALL_SKIP_SYNC=1`.
- If `sync-all` fails, installer must try `tradecat sync signal_flow` so the default no-argument TUI has the highest chance of showing data.
- TUI must stay cache-first and must not block startup on remote CSV fetch.
- Empty cache must be diagnostic: status bar exposes `cold-start=warming`, `cold-start=sync-needed`, or `cold-start=probe-failed`.
- Weak-network guidance must point to `tradecat config set tui_fetch_timeout.signal_flow 3` and `tradecat sync-all`.

## Operator Commands

```bash
tradecat doctor
tradecat doctor --sync --timeout 10
tradecat sync-all
tradecat sync-all --timeout 10
tradecat config set tui_fetch_timeout.signal_flow 3
tradecat config set tui_probe_interval.signal_flow 3
```

## Verification

```bash
tradecat status --json
tradecat tui signal_flow --plain --limit 3
```

Expected status after recovery: `ready_dataset_count=5` and `missing_dataset_count=0`.
