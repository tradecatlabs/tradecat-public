# Contributing

TradeCat Public 是一个公开安全的 Agent/Hermes 纸面交易运行时。贡献流程的目标是让每次改动都可审查、可验证、可回滚，并且不突破 public-readonly + paper/watch 边界。

## 分支

- `main`: 发布基线，必须保持可发布状态。
- `develop`: 日常集成分支。
- `feature/<topic>`: 新能力或治理改进。
- `fix/<topic>`: 缺陷修复。
- `release/<version>`: 发布准备，可选。
- `hotfix/<topic>`: 紧急修复。

不要直接向 `main` 推送。GitHub 分支保护应要求 PR、至少 1 名 review、CI 通过和最新分支检查。

## 提交

使用 Conventional Commits：

```text
feat(scope): add capability
fix(scope): correct behavior
docs(scope): update guide
refactor(scope): simplify boundary
test(scope): cover regression
chore(scope): update tooling
ci(scope): adjust workflow
perf(scope): improve hot path
```

一次提交只做一件事。不要把格式化、文档、业务逻辑、测试和运行态输出混在同一个提交里，除非它们是同一验证闭环的最小集合。

## Pull Request

每个 PR 必须说明：

- 改了什么。
- 为什么改。
- 如何验证。
- 影响范围和回滚方式。
- 是否触碰交易安全边界。

PR 不应提交 `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/`、`.tools/`、`project/`、`tasks/` 或任何凭证、日志、账本、缓存。

## 本地验证

改动提交前至少运行：

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

定向开发时可先运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_service.py tests/test_paper_ledger.py
PYTHONPATH=src ruff check src tests
PYTHONPATH=src ruff format --check src tests scripts
```

## Review 标准

Review 优先看正确性、安全边界、schema/provenance、fail-closed、运行态隔离和测试证据。评论必须具体到文件、行为和期望结果。

## 发布

发布使用语义化版本 `MAJOR.MINOR.PATCH`。发布前更新 `CHANGELOG.md`，确认 CI、secret scan、supply-chain audit、Skill strict 和 agent smoke 全部通过，然后打 tag。
