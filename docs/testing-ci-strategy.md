# Testing and CI Strategy

TradeCat Public 的测试目标不是覆盖所有通用测试名词，而是把本仓库的真实风险面变成可执行门禁：公开信号源、Agent 输入契约、public-readonly 安全边界、paper ledger、运行态隔离、可复现审计和 CI/CD 本身。

机器主清单位于 `resources/test_ci_matrix.json`。文档解释测试分层；`scripts/validate_testing_ci_contract.py` 负责验证清单、测试证据、CI workflow 和本地 verify 是否一致。

## 测试分层

| 层级 | 本仓库对应范围 | 证据 |
| --- | --- | --- |
| 单元 / 函数测试 | signal scoring、strategy intent、risk policy、paper broker、ledger math、market enrichment | `tests/test_signals.py`、`tests/test_strategies.py`、`tests/test_risk.py`、`tests/test_paper_ledger.py` |
| 契约测试 | JSON Schema、Agent context、trade thesis、Skill manifest、payload safety | `contracts/`、`tests/test_agent_contract.py`、`tests/test_payload_schema_validation.py`、`tests/test_agent_market_context.py` |
| 服务 / 集成测试 | `run_service_cycle`、paper ledger、audit journal、production reports、replay | `tests/test_service.py`、`tests/test_audit_journal.py`、`tests/test_production_control.py`、`tests/test_replay_reporting.py` |
| 数据流测试 | `signal_flow`、`anomaly_panel`、dataset registry、source normalization | `tests/test_tradecat_source.py`、`tests/test_dataset_consumption_contract.py` |
| 并发 / 幂等测试 | ledger lock、state/archive/CLI JSONL lock、重复事件、重复 execution id | `tests/test_paper_ledger.py`、`tests/test_service.py`、`tests/test_cli_runtime.py` |
| 安全测试 | secret scan、public repo guard、false-only safety flags、dependency policy | `scripts/security-scan.sh`、`tests/test_safety_boundary.py`、`tests/test_public_repo_guardrails.py` |
| 运维 / 冒烟测试 | auto-paper status、ops-check、health、agent readiness | `scripts/agent-smoke.sh`、`tests/test_auto_service_script.py` |
| CI/CD 契约测试 | GitHub Actions、本地 verify、测试矩阵和关键门禁不能漂移 | `scripts/validate_testing_ci_contract.py`、`tests/test_testing_ci_contract.py` |

## 当前不适用的测试

- UI / 浏览器 / 移动端测试：本仓库没有正式前端产品；本地监控页面只作为 paper/watch 运维观察窗口。
- 数据库迁移测试：没有生产数据库；SQLite audit journal 是 ignored 本地运行态。
- 实盘订单、账户、签名接口测试：明确不属于 `tradecat-public`，未来若需要应在私有 executor 仓库实现。
- DAST / 渗透测试：当前没有公网 Web 服务；安全重点是 secret scan、public-readonly guard、依赖扫描和契约拒绝。
- 容器 / K8s / Helm 发布测试：当前没有 Dockerfile、K8s manifest 或 Helm chart。

## CI/CD 门禁

GitHub Actions 在 `.github/workflows/ci.yml` 中执行：

- Top-level `permissions: contents: read`，避免默认写权限。
- Top-level `concurrency`，同一 ref 的旧 run 会被取消，减少重复 CI 消耗。
- Job-level `timeout-minutes`，防止测试、网络或供应链扫描卡死。
- Checkout `persist-credentials: false`，避免把 GitHub token 留给后续步骤。
- Skill strict validation。
- Secret scan。
- Dependency policy。
- Testing/CI contract validation。
- Ruff lint 和 format check。
- Pytest 全量回归。
- Data contract validators。
- Supply-chain audit。
- Shell/Python syntax check。
- Wheel package data check。
- Agent readiness smoke。

本地 `bash scripts/verify.sh` 会通过 `scripts/verify-project.sh` 执行同一组核心门禁。任何新增测试层、CI step、脚本入口或关键命令变化，都必须同步更新 `resources/test_ci_matrix.json`，否则 `scripts/validate_testing_ci_contract.py` 会失败。
