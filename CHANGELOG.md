# Changelog

本项目遵循语义化版本。所有公开可见的能力、治理变更和安全边界变化都应记录在这里。

## Unreleased

- Added repository collaboration governance: contribution rules, PR template, CODEOWNERS, editor settings, environment example, Dependabot config, and standard docs entrypoints.
- Added formatting and dependency policy gates to keep future changes reviewable.

## v0.1.3 - 2026-05-18

- Restructured TradeCat Public as a repository-root Python project with an embedded `skills/tradecat-public/` Skill package.
- Retired the local TUI, installer, watchdog, and cache-browser product surfaces.
- Kept the public online sheet signal adapter, Agent-supplied Binance market context contracts, paper/watch runtime, ledger, risk, reports, and audit outputs.
- Ignored local task and retired project workspaces so they cannot enter the public repository.

## v0.1.2 - 2026-05-18

- Hardened TradeCat Skill package governance, Agent manifest paths, and runtime boundary checks.
- Added or aligned Binance public-readonly resource snapshots and provenance validation.

## v0.1.1 - 2026-05-18

- Hardened paper contract outputs, safety fields, structured error codes, and Agent thesis validation.

## v0.1.0 - 2026-05-18

- Established the initial public Agent paper-trading contract layer.
