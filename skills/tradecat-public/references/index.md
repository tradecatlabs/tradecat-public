# TradeCat Public References

Start from `SKILL.md`. Load only the reference needed for the current task.

## Load Order

1. Skill package shape, role/profile placement, layout, movement rules, or root cleanliness: `skill-package-governance.md`, then `architecture.md`, then `quality-gate.md`.
2. Agent/Hermes machine contract, command risk classes, JSON schemas, and safety rules: `agent-contract.md`.
3. Human + Hermes operating guide for development/production boundary, Agent-supplied market context, and paper runtime: `hermes-agent-guide.md`.
4. Agent soft decision layer, prompts, endpoint policy, thesis contract, and hard account/order boundaries: `agent-soft-decision-layer.md`.
5. Dataset field semantics, missing values, time grain, and quality tier: `dataset-consumption-contract.md`.
6. End-to-end public signal, Agent context, paper/watch, report, and monitor flows: `linear-flows.md`.
7. QA strategy, risk model, test layers, and delivery gate: `test-strategy.md`.
8. Future real-money execution boundary: `private-executor-boundary.md`.
9. Autonomous paper/watch operations dependency chain: `autonomous-paper-ops.md`.
10. Repository collaboration, release, deployment, and configuration: root `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/configuration.md`, `docs/deployment.md`, and `docs/release.md`.

## Reference Map

- `skill-package-governance.md`: embedded Hermes Skill package governance and retired local TUI/install product boundary.
- `architecture.md`: repository-root Python project, embedded Skill package, signal source adapter, Binance resource snapshots, and paper/watch runtime architecture.
- `agent-contract.md`: canonical Agent consumption contract, risk classes, JSON schemas, public-readonly endpoint policy, and fail-closed paper rules.
- `hermes-agent-guide.md`: operating guide for Hermes/Agent loops, local runtime, monitor, and validation.
- `agent-soft-decision-layer.md`: Agent/Hermes soft prompt layer and account/order safeguard policy.
- `dataset-consumption-contract.md`: machine-readable public sheet dataset semantics.
- `linear-flows.md`: linear flows for public signals, research cycle, context audit, paper runtime, reports, and validation.
- `test-strategy.md`: QA entrypoint covering product understanding, module risk matrix, automation layers, and regression checklist.
- `quality-gate.md`: pre-delivery checklist, validation commands, boundary audit, and safety evidence.
- `private-executor-boundary.md`: public TradeCat paper/watch output versus future private real-money executor responsibilities.
- `autonomous-paper-ops.md`: long-running auto-paper dependency chain, preflight, lifecycle, health, logging, limits, recovery, and safety boundaries.
- Root collaboration docs: `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/configuration.md`, `docs/deployment.md`, and `docs/release.md` are human workflow docs; they must not override the Agent manifest or JSON schemas.
- `archive/`: historical repair/task references only; not current implementation guidance.

## Source Rule

The Python project lives at the repository root. The Skill package lives at `skills/tradecat-public/`. Public online sheet input code lives in `src/tradecat_sources/`; Agent context, paper/watch, ledger, risk, and reports live in `src/tradecat_auto/`. Do not recreate retired `src/tradecat_terminal/`, installers, or TUI flows.
