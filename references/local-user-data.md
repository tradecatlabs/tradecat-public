# Local user/runtime data policy

TradeCat is maintained as a public repository. Local user data is allowed during development and paper testing, but real local state must not be committed.

## Commit to git

- Public source code and tests.
- JSON Schemas and machine-readable contracts.
- Sanitized examples and tiny fixtures that contain no account data, credentials, private URLs, or real local ledger history.
- Template files such as `.env.example` or `*.example.json`.
- Documentation that explains where runtime files live.

## Do not commit

- `.env`, `*.env`, `.env.*` except `.env.example`.
- API keys, secrets, tokens, private keys, certificates, or credential dumps.
- Local runtime directories such as `.runtime/`, `.tradecat/`, `.hermes/`, `.local/`, `user-data/`, `local-data/`, and `private-data/`.
- Paper-trading/user-state artifacts such as `paper_ledger*.json`, `cycles*.jsonl`, `service_state*.json`, `run_loop_smoke*.json`, local logs, SQLite/DB files, cache files, and account/order exports.
- Any real Binance account state, real orders, real fills, private balances, or reusable credentials.

## Required pattern

Keep real user/runtime data outside versioned source, or under ignored local runtime paths. If a data shape must be documented, create a sanitized fixture or `*.example.json` file with fake values only.

Before any commit, run the repository security and status checks and verify that ignored runtime paths remain untracked.
