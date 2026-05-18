## What changed

- 

## Why

- 

## How tested

- [ ] `bash scripts/agent-smoke.sh`
- [ ] `bash scripts/verify.sh`
- [ ] `bash scripts/validate-skill.sh --strict`
- [ ] `bash scripts/security-scan.sh`
- [ ] `bash scripts/supply-chain-audit.sh`
- [ ] `git diff --check`

## Safety boundary

- [ ] Public/read-only market data only
- [ ] Paper/watch only
- [ ] No Binance key/secret/listen key reads
- [ ] No signed requests
- [ ] No account/order/leverage/margin private endpoints
- [ ] No real orders
- [ ] No default sizing/exits invented by TradeCat

## Risk and rollback

- Risk:
- Rollback:
