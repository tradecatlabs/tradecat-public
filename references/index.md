# TradeCat Public References

Start from `SKILL.md`. Load these references only when the task needs their contract.

## Load Order

1. Layout, movement rules, or root cleanliness: `architecture.md`, then `quality-gate.md`.
2. Cache, export, sync, prune, doctor, or local repair behavior: `cache-contract.md`.
3. TUI startup, live probe, rendering, language, or links: `tui-contract.md`.
4. Installer, launcher update, or uninstall behavior: `install-uninstall.md`.
5. First-run empty cache, cold-start, or weak-network diagnosis: `first-run-cache.md`.
6. End-to-end public data and install flows: `linear-flows.md`.
7. Agent/Hermes machine contract, fast path, command risk classes, and JSON schemas: `agent-contract.md`.
8. Release notes, install evidence, and rollback: `release.md`.
9. Stability hardening backlog and execution waves: `stability-hardening-task-tree.md`.
10. Agent/Hermes readiness remediation backlog and execution waves: `agent-readiness-remediation-task-tree.md`.
11. Post-signoff Agent contract maturity hardening: `agent-contract-maturity-task-tree.md`.

## Reference Map

- `architecture.md`: Skill root scope, forbidden paths, source boundaries, documentation map, and linear data flow.
- `cache-contract.md`: snapshot cache, stream merge, structured latest files, export behavior, and manifest rules.
- `tui-contract.md`: TUI startup, background probe, rendering, language, terminal fallback, and link behavior.
- `install-uninstall.md`: installer, launcher auto-update, uninstall behavior, and cache preservation.
- `first-run-cache.md`: cold-start cache diagnosis, prevention rules, operator commands, and verification.
- `linear-flows.md`: seven public linear flows covering cache sync, TUI, one-shot request, install, uninstall, config/export, and doctor diagnostics.
- `agent-contract.md`: canonical multi-Agent consumption contract, fast path, risk classes, exit codes, JSON schema names, and transport split.
- `quality-gate.md`: pre-delivery checklist, validation commands, root/project boundary audit, and release evidence.
- `release.md`: public release notes, CI evidence, fixed-ref install commands, known limits, and rollback.
- `stability-hardening-task-tree.md`: current TP-XX stability and robustness hardening backlog, execution waves, ready leaves, gates, and validation plan.
- `stability-hardening-task-tree.json`: machine-readable current hardening task tree spec.
- `agent-readiness-remediation-task-tree.md`: TP-XX task tree for turning TradeCat into a strict multi-Agent/Hermes-consumable Skill repository.
- `agent-readiness-remediation-task-tree.json`: machine-readable Agent readiness task tree spec.
- `agent-contract-maturity-task-tree.md`: non-blocking post-signoff task tree for schema coverage, manifest consistency, and smoke error semantics.
- `agent-contract-maturity-task-tree.json`: machine-readable Agent contract maturity task tree spec.
- `archive/repair-task-tree.md`: completed historical TP-XX remediation tree, kept only for audit evidence.
- `archive/repair-task-tree.json`: machine-readable archived task tree spec.

## Source Rule

The bundled project lives in `scripts/project/`. Load project source files only when the task requires code-level changes.
