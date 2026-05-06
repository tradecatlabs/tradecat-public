# TUI Contract

The TUI is a cache-first terminal browser over local JSON cache files.

## Startup

- `tradecat` without arguments opens TUI.
- Default dataset is `event_stream`.
- Startup must not block on remote CSV fetching.
- Plain mode and fallback render from cache only.

## Probing

- Live probe runs in background threads, not inside the curses draw path.
- Current focused dataset uses dataset-specific probe interval.
- Non-focused active datasets are refreshed in background.
- Consecutive probe failures back off: 1 failure at least 3s, 2 failures at least 5s, 3+ failures at least 15s.
- Fetch timeout is dataset-specific and capped by interval.

## Rendering

- Keep table top columns as physical `A/B/C...`.
- Header aliases only enter metadata, not the visible top-level table columns.
- No frozen columns and no right-side horizontal table scrolling.
- Width is based on real content display width; terminal viewport crops visible output.
- `event_stream` uses a lightweight two-column path.

## Terminal Compatibility

- Windows native, Web SSH, and no-curses environments use Rich plain fallback.
- Fallback must be borderless and width-capped, not psql bordered.
- Known stable terminals may use curses.

## Interaction

- `?` opens help.
- Search filters only the current view and never writes cache.
- URL text opens the URL directly.
- Symbol links open Binance Futures when inferred from visible symbol cells.
