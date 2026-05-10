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

- Expand formal schema coverage for every JSON output advertised in
  `agents/manifest.json`.
- Add manifest consistency tests for schema references, version pins, known
  failure codes, and manifest/schema-file 1:1 coverage.
- Validate real CLI/request JSON payloads against the formal schema files.
- Add golden JSON fixtures for common Agent success/failure interpretations.
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

- Schema files exist for `init`, `status`, `doctor`, `path`, `datasets`,
  `sync`, `sync-all`, single-dataset `probe --no-write`, all-dataset
  `probe --no-write`, `prune`, `config`, `request`, `request --datasets`,
  `export`, and `doctor --bundle`.
- Each schema pins the advertised `schema` and `schema_version`.
- Manifest-advertised JSON outputs and command-level schema files stay 1:1.
- Generic envelope and error schemas remain the shared base.

### TP-02: Manifest Consistency Tests

Owner: test suite.

Acceptance:

- Manifest JSON output commands and schemas are unique.
- Entrypoint schema references are declared in `json_outputs`.
- Required Agent failure codes remain advertised.
- Command schema files are valid JSON and pin the expected schema names.
- `tradecat.watch_cycle.v1` remains explicitly allowlisted as a CLI-internal
  schema until it is intentionally promoted.

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
- `doctor --json`, `config show --json`, dry-run `prune --json`, single-dataset
  `probe --json --no-write`, and all-dataset `probe --json --no-write` stay in
  the smoke gate.

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

### TP-06: Real Payload Schema Validation

Owner: test suite.

Acceptance:

- Live CLI payloads for manifest-advertised JSON surfaces validate against
  their formal schema files.
- `scripts/project/scripts/request.py` success payloads validate without
  network by using a local fake registry/fetch path.
- Invalid dataset, invalid runtime configuration, and local runtime failure
  payloads validate as `ok=false` schema payloads with stable error objects.
- `jsonschema` is present only in the project dev dependencies and
  `constraints.txt`; runtime dependencies stay unchanged.

### TP-07: Golden JSON Fixtures

Owner: contract governance.

Acceptance:

- Golden samples live under
  `scripts/project/tests/fixtures/json_contract/`.
- Fixtures cover status success, request dataset list success, support bundle
  success, invalid dataset, invalid runtime configuration, and local runtime
  error.
- Fixture files validate against the same formal schema helper used for live
  payloads.

## Completion Rule

This wave is complete when the schema coverage, tests, smoke gate, and public
reference updates are committed together. Payload validation and fixture updates
may extend this hardening wave as long as they do not change user-facing CLI
semantics. Any future behavior-changing CLI work must use a separate task tree.
