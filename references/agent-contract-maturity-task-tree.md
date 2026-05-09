# Agent Contract Maturity Task Tree

Status: implemented in the current non-blocking hardening wave.

This tree starts after the `ddd57b1` sign-off point. It does not reopen the
accepted CLI behavior contract; it tightens the machine contract around it so
future Agents can detect drift earlier.

## Goal

Make the signed-off Agent-ready contract harder to regress without adding new
runtime dependencies or changing the TradeCat user workflow.

## Scope

Included:

- Expand formal schema coverage for high-value JSON outputs.
- Add manifest consistency tests for schema references, version pins, and known
  failure codes.
- Extend `scripts/agent-smoke.sh` to assert runtime configuration error
  classification, not only invalid dataset classification.
- Document the maturity layer in public references.

Excluded:

- Rewriting CLI command behavior.
- Adding a JSON Schema validation runtime dependency.
- Turning every CLI output into a fully strict closed-world schema.
- Changing install, cache, TUI, or remote fetch semantics.

## Task Tree

### TP-01: Command Schema Coverage

Owner: contract governance.

Acceptance:

- Schema files exist for `init`, `status`, `datasets`, `sync`, `sync-all`,
  `request`, `request --datasets`, `export`, and `doctor --bundle`.
- Each schema pins the advertised `schema` and `schema_version`.
- Generic envelope and error schemas remain the shared base.

### TP-02: Manifest Consistency Tests

Owner: test suite.

Acceptance:

- Manifest JSON output commands and schemas are unique.
- Entrypoint schema references are declared in `json_outputs`.
- Required Agent failure codes remain advertised.
- Command schema files are valid JSON and pin the expected schema names.

### TP-03: Agent Smoke Error Semantics

Owner: shell gate.

Acceptance:

- `agent-smoke` still validates skill strict, manifest JSON, schema JSON, and
  readonly fast path commands.
- Invalid dataset failures return non-zero with `invalid_dataset_key`.
- Invalid runtime configuration returns rc `2` with
  `invalid_runtime_configuration`.
- The runtime configuration test uses a local fake fetch and writes only to a
  temporary cache directory.

### TP-04: Documentation Indexing

Owner: public references.

Acceptance:

- `references/index.md` links this maturity task tree.
- `references/agent-contract.md` lists command schema coverage and clarifies the
  maturity boundary.
- `references/quality-gate.md` names the strengthened agent smoke and manifest
  consistency checks.

### TP-05: Validation And Delivery

Owner: release operator.

Acceptance:

- `bash scripts/agent-smoke.sh` passes.
- `bash scripts/verify.sh` passes.
- `bash scripts/security-scan.sh` passes.
- `bash scripts/supply-chain-audit.sh` passes.
- `git diff --check` passes.

## Completion Rule

This wave is complete when the schema coverage, tests, smoke gate, and public
reference updates are committed together. Any future behavior-changing CLI work
must use a separate task tree.
