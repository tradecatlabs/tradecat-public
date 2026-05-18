# Private Executor Boundary

`tradecat-public` is the public Hermes Skill and paper/watch contract layer. It
must never become a real-money executor.

## Public Repo Responsibilities

- Consume public sheet signals and Agent-supplied Binance public/read-only market context.
- Validate schema/version/provenance/safety fields.
- Run context audit, paper/watch pipeline, paper ledger, risk rejection, replay, and reports.
- Emit audited local paper/watch intent and evidence only.

## Private Executor Responsibilities

A future private executor, in a separate private repository and runtime, is the
only place that may:

- Read exchange API keys or secrets.
- Sign Binance requests.
- Read real account, balance, position, order, or user-trade state.
- Place, amend, cancel, or reconcile real orders.
- Enforce real-money permissions, kill switch, and operator approval.

## Boundary Contract

Public output may be consumed by a private executor only after it is audited and
paper/watch safe. The public payload must include schema, schema_version,
error_code, provenance, and safety fields. It must not include credentials,
signature material, listen keys, private endpoints, or real exchange order IDs.

The draft handoff schema is
`project/contracts/tradecat-auto-audited-intent-handoff.schema.json` with
`schema=tradecat_auto.audited_intent_handoff.v1`. It is a sanitized candidate
intent, not a Binance order request.

The private executor must treat public TradeCat output as an input candidate, not
as an order. It must re-check risk, permissions, account state, and operator
policy before any real execution.
