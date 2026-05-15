# Agent Soft Layer Resources

This directory contains the self-contained soft layer that Hermes/Agent can load before producing Agent-supplied market context or a paper-only trade thesis for TradeCat.

## What this is

- Prompt templates under `prompts/` for research/context gathering and thesis generation.
- `endpoint_policy.json`, an extracted public USDⓈ-M context catalog from the bundled Binance skill/API snapshots.
- A soft contract: Agent reasoning stays in prompts and JSON thesis fields; deterministic TradeCat code still owns schema audit, account/order safety, risk rejection, paper ledger mutation, and replay.

## What this is not

- Not a Binance runtime client.
- Not a signed endpoint adapter.
- Not a real account/order importer.
- Not permission to read Binance keys or place/cancel/modify orders.

## Hard boundary

If an Agent needs account/order state for a prompt, it must use TradeCat's local paper ledger/account-state contract, never Binance account/order endpoints. `tradecat_auto.agent_market_context` rejects credential-like material, signed/account/order endpoints, and real account/order state keys before `run-context` can proceed.
