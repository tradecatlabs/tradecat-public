# TradeCat Public References

Start from `SKILL.md`. Load these references only when the task needs their contract.

## Load Order

1. Layout, movement rules, or root cleanliness: `architecture.md`, then `quality-gate.md`.
2. Cache, export, sync, or prune behavior: `cache-contract.md`.
3. TUI startup, live probe, rendering, language, or links: `tui-contract.md`.
4. Installer, launcher update, or uninstall behavior: `install-uninstall.md`.
5. First-run empty cache, cold-start, or weak-network diagnosis: `first-run-cache.md`.
6. End-to-end public data and install flows: `linear-flows.md`.
7. Release notes, install evidence, and rollback: `release.md`.

## Reference Map

- `architecture.md`: Skill root scope, forbidden paths, source boundaries, documentation map, and linear data flow.
- `cache-contract.md`: snapshot cache, stream merge, structured latest files, export behavior, and manifest rules.
- `tui-contract.md`: TUI startup, background probe, rendering, language, terminal fallback, and link behavior.
- `install-uninstall.md`: installer, launcher auto-update, uninstall behavior, and cache preservation.
- `first-run-cache.md`: cold-start cache diagnosis, prevention rules, operator commands, and verification.
- `linear-flows.md`: six public linear flows covering cache sync, TUI, one-shot request, install, uninstall, and config/export.
- `quality-gate.md`: pre-delivery checklist, validation commands, root/project boundary audit, and release evidence.
- `release.md`: public release notes, CI evidence, fixed-ref install commands, known limits, and rollback.
- `archive/repair-task-tree.md`: completed historical TP-XX remediation tree, kept only for audit evidence.
- `archive/repair-task-tree.json`: machine-readable archived task tree spec.

## Source Rule

The bundled project lives in `scripts/project/`. Load project source files only when the task requires code-level changes.
