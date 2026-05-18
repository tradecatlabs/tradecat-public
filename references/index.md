# TradeCat Public References

Start from `SKILL.md`. Load these references only when the task needs their contract.

## Load Order

1. Skill package shape, role/profile placement, layout, movement rules, or root cleanliness: `skill-package-governance.md`, then `architecture.md`, then `quality-gate.md`.
2. Cache, export, sync, prune, doctor, or local repair behavior: `cache-contract.md`.
3. TUI startup, live probe, rendering, language, or links: `tui-contract.md`.
4. Installer, launcher update, or uninstall behavior: `install-uninstall.md`.
5. First-run empty cache, cold-start, or weak-network diagnosis: `first-run-cache.md`.
6. End-to-end public data, automation, and install flows: `linear-flows.md`.
7. Local user/runtime data handling for the public repo: `local-user-data.md`.
8. Agent/Hermes machine contract, fast path, command risk classes, and JSON schemas: `agent-contract.md`.
9. Human + Hermes operating guide for development/production boundary, skill install, and Agent-supplied market context: `hermes-agent-guide.md`.
10. Agent soft decision layer, prompts, endpoint policy, thesis contract, and hard account/order boundaries: `agent-soft-decision-layer.md`.
11. Dataset field semantics, missing values, time grain, and quality tier: `dataset-consumption-contract.md`.
12. Analysis report contract, boundaries, and no-trading-advice scope: `analysis-contract.md`.
13. Symbol feature facts contract and no-signal boundary: `feature-contract.md`.
14. QA strategy, risk model, test layers, and release test gate: `test-strategy.md`.
15. Release notes, install evidence, and rollback: `release.md`.
16. Stability hardening backlog and execution waves: `stability-hardening-task-tree.md`.
17. Agent/Hermes readiness remediation backlog and execution waves: `agent-readiness-remediation-task-tree.md`.
18. Post-signoff Agent contract maturity hardening: `agent-contract-maturity-task-tree.md`.
19. Future real-money execution boundary: `private-executor-boundary.md`.
20. Autonomous paper/watch operations dependency chain: `autonomous-paper-ops.md`.

## Reference Map

- `skill-package-governance.md`: Hermes Skill 包形态、根目录职责、`project/` 内部项目边界、Agent/交易员 role profile 和运行态隔离规则。
- `architecture.md`: Skill root scope, forbidden paths, source boundaries, merged `tradecat_auto` lifecycle layer, documentation map, and linear data flow.
- `cache-contract.md`: snapshot cache, stream merge, structured latest files, export behavior, and manifest rules.
- `tui-contract.md`: TUI startup, background probe, rendering, language, terminal fallback, and link behavior.
- `install-uninstall.md`: installer, launcher auto-update, uninstall behavior, and cache preservation.
- `first-run-cache.md`: cold-start cache diagnosis, prevention rules, operator commands, and verification.
- `linear-flows.md`: public linear flows covering cache sync, TUI, one-shot request, install, uninstall, config/export, doctor diagnostics, analysis report, feature bundle, paper/watch automation, and Agent fast path.
- `local-user-data.md`: public-safe policy for managing local user/runtime data, ignored files, sanitized fixtures, and non-commit boundaries.
- `agent-contract.md`: canonical multi-Agent consumption contract, fast path, risk classes, exit codes, JSON schema names, and transport split.
- `hermes-agent-guide.md`: human/Hermes operating guide for development-vs-production boundaries, local skill installation, Agent-supplied market context, safety boundaries, and validation checklist.
- `agent-soft-decision-layer.md`: Agent/Hermes soft prompt layer, endpoint policy, paper-only thesis schema, and hard account/order state safeguards.
- `dataset-consumption-contract.md`: machine-readable dataset field semantics, missing values, time grain, and quality tier.
- `analysis-contract.md`: readonly local analysis report contract and explicit boundary against strategy, backtest, advice, or execution semantics.
- `feature-contract.md`: per-symbol feature facts contract and explicit boundary against signal, score, strategy, or execution semantics.
- `test-strategy.md`: QA entrypoint covering product understanding, module risk matrix, automation layers, release gate, regression checklist, and defect template.
- `quality-gate.md`: pre-delivery checklist, validation commands, root/project boundary audit, and release evidence.
- `private-executor-boundary.md`: public TradeCat paper/watch output versus future private real-money executor responsibilities.
- `autonomous-paper-ops.md`: long-running auto-paper dependency chain, preflight, lifecycle, health, logging, limits, recovery, and safety boundaries.
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

The bundled project lives in `project/`. Load project source files only when the task requires code-level changes.
