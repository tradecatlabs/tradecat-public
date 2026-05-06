# TradeCat Public References

Start from `SKILL.md`. Load these references only when the task needs their contract.

## Load Order

1. Layout, movement rules, or root cleanliness: `architecture.md`, then `quality-gate.md`.
2. Cache, export, sync, or prune behavior: `cache-contract.md`.
3. TUI startup, live probe, rendering, language, or links: `tui-contract.md`.
4. Installer, launcher update, or uninstall behavior: `install-uninstall.md`.
5. End-to-end public data and install flows: `linear-flows.md`.
6. WARN finding remediation planning: `repair-task-tree.md` and `repair-task-tree.json`.

## Reference Map

- `architecture.md`: Skill root scope, forbidden paths, source boundaries, documentation map, and linear data flow.
- `cache-contract.md`: snapshot cache, stream merge, structured latest files, export behavior, and manifest rules.
- `tui-contract.md`: TUI startup, background probe, rendering, language, terminal fallback, and link behavior.
- `install-uninstall.md`: installer, launcher auto-update, uninstall behavior, and cache preservation.
- `linear-flows.md`: six public linear flows covering cache sync, TUI, one-shot request, install, uninstall, and config/export.
- `quality-gate.md`: pre-delivery checklist, validation commands, root/project boundary audit, and release evidence.
- `repair-task-tree.md`: human-readable TP-XX remediation tree for the current WARN findings.
- `repair-task-tree.json`: machine-readable recursive task tree spec rendered by auto-tasks tooling.

## Source Rule

The bundled project lives in `scripts/project/`. Load project source files only when the task requires code-level changes.
