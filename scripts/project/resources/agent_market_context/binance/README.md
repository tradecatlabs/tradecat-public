# Binance Agent Market Context Resources

This directory is a local, self-contained reference snapshot for Agent/Hermes-supplied Binance market context in TradeCat.

## Contents

- `upstream/binance-skills-hub-main/`: read-only copy of the provided Binance Skills Hub snapshot.
- `api-docs/币安全部api.md`: read-only copy of the provided archived Binance API analysis document.
- `api-docs/币安API完整文档汇总.md`: read-only copy of the provided archived Binance API summary document.
- `provenance.manifest.json`: machine-readable copy provenance, checksums, safety scan summary, and TradeCat boundary contract.

## TradeCat boundary

These files are reference material only. TradeCat may use them to guide Agent-supplied market context, but the current project boundary remains `public_readonly + paper/watch`:

- allowed: public Binance USDⓈ-M market data such as klines, order book/depth, book ticker, 24h ticker, funding, premium index, open interest, long/short ratios, and taker buy/sell volume;
- forbidden: Binance API keys, signed requests, account reads, real orders, order cancel/modify, leverage changes, margin changes, and any mainnet execution path.

The upstream skill mirror includes authenticated and trading endpoint documentation. Those files are intentionally preserved for provenance, but they are not active TradeCat runtime tools until a future explicit adapter contract restricts them behind deterministic safety gates.

Copied at: `2026-05-15T16:55:43+08:00`.
