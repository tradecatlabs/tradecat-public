# Release Process

TradeCat Public 使用语义化版本：

```text
MAJOR.MINOR.PATCH
```

## 发布步骤

1. 更新 `pyproject.toml` 的版本号。
2. 更新 `CHANGELOG.md`，把 `Unreleased` 内容归档到目标版本。
3. 运行完整门禁：

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

4. 确认 `real_orders=false`、`signed_requests=false`、`reads_api_keys=false` 仍成立。
5. 创建 tag：

```bash
git tag vMAJOR.MINOR.PATCH
git push origin vMAJOR.MINOR.PATCH
```

## 不发布的内容

- `.runtime/`
- `.tradecat/`
- `.venv/`
- `.hermes/`
- `.tools/`
- `project/`
- `tasks/`
- 凭证、日志、账本、缓存、真实账户输出
