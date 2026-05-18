# Execution Checklist
[x] TP-01.01 | P0 | 确认工作树与运行态 | Verify: git status --short --branch；bash scripts/start-auto-paper.sh status --json；PYTHONPATH=src python3 -m tradecat_auto.cli health-report --json | Gate: 状态证据足够支持后续补丁或提交决策。 | Parallelizable: No
[x] TP-01.02 | P0 | 收口 agent_trade_thesis helper | Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_service.py | Gate: agent_trade_thesis 不再是漂移的未定义输入面。 | Parallelizable: No
[x] TP-01.03 | P0 | 验证 paper/watch 安全边界 | Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py | Gate: 安全字段与拒绝行为符合公开仓库边界。 | Parallelizable: Yes
[x] TP-01.04 | P0 | 形成 P0 交付证据 | Verify: bash scripts/verify.sh && git diff --check && git status --short --branch | Gate: P0 可作为 P1 契约设计的稳定起点。 | Parallelizable: No
[x] TP-02.01 | P0 | 设计 agent_research_cycle.v1 schema | Verify: schema fixture validation test | Gate: 契约足以表达一轮 Agent 自主研究，不含真实交易执行字段。 | Parallelizable: No
[x] TP-02.02 | P0 | 补 research cycle fixtures | Verify: pytest contract fixture tests | Gate: fixture 能覆盖后续 loop 的核心行为。 | Parallelizable: No
[x] TP-02.03 | P0 | 实现 research cycle validator | Verify: PYTHONPATH=src python3 -m pytest tests/test_agent_research_cycle.py | Gate: research cycle 可作为 Agent loop 的单一输入输出契约。 | Parallelizable: No
[x] TP-02.04 | P1 | 更新 Agent 文档和 manifest 索引 | Verify: bash scripts/validate-skill.sh --strict | Gate: Agent/Hermes 能从 Skill 包理解 research loop 契约。 | Parallelizable: No
[x] TP-03.01 | P0 | 新增 observe-only loop 入口 | Verify: 定向 pytest + CLI smoke | Gate: 可以稳定生成一轮研究任务。 | Parallelizable: No
[x] TP-03.02 | P0 | 固化 Binance public-readonly 工具编排 | Verify: context-audit fixture tests | Gate: Agent 工具调用顺序可审计、可复现。 | Parallelizable: No
[x] TP-03.03 | P0 | 生成 context/thesis 草案输出 | Verify: pytest + json schema validation | Gate: observe-only 产物可被 context-audit 消费。 | Parallelizable: No
[x] TP-03.04 | P0 | 串接 context-audit 但不执行 paper | Verify: bash scripts/agent-smoke.sh 或定向 observe smoke | Gate: observe-only loop 可以安全接入 Hermes。 | Parallelizable: No
[x] TP-04.01 | P0 | 实现 audit -> paper gate | Verify: pytest run-context failure paths | Gate: paper 开仓只能来自合格 Agent thesis。 | Parallelizable: No
[x] TP-04.02 | P0 | 执行 thesis-driven paper run | Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py | Gate: paper execution 与 Agent thesis 字段一致。 | Parallelizable: No
[x] TP-04.03 | P1 | 接入 ledger/journal/health | Verify: paper-report/health-report/audit-journal 定向测试 | Gate: paper 运行结果可审计。 | Parallelizable: No
[x] TP-04.04 | P1 | 定义连续 paper 服务模式 | Verify: service tests + start-auto-paper status smoke | Gate: 连续 paper 服务不会和 observe-only 输出互相踩写。 | Parallelizable: No
[x] TP-05.01 | P1 | 标准化 paper account state 输入 | Verify: paper_account_state tests | Gate: Agent 不会误把本地 paper 状态当真实账户。 | Parallelizable: No
[x] TP-05.02 | P1 | 定义 position_management_thesis.v1 | Verify: schema validation tests | Gate: 仓位管理 thesis 可被机器审计。 | Parallelizable: No
[x] TP-05.03 | P1 | 实现 paper 仓位动作应用层 | Verify: paper ledger position management tests | Gate: 持续仓位管理仍是 paper-only。 | Parallelizable: No
[x] TP-06.01 | P1 | 统一 decision trace | Verify: replay trace fixture tests | Gate: 复盘可解释每次开仓或拒绝。 | Parallelizable: No
[x] TP-06.02 | P1 | 生成 decision quality report | Verify: quality report tests | Gate: Codex loop 可用报告推进工程迭代。 | Parallelizable: No
[x] TP-06.03 | P1 | 验证 replay 可复现 | Verify: pytest replay tests | Gate: 审计与回测闭环可信。 | Parallelizable: No
[x] TP-07.01 | P1 | 定义 portfolio risk policy | Verify: risk schema tests | Gate: policy 可由 Agent/operator 明确配置。 | Parallelizable: No
[x] TP-07.02 | P1 | 实现 portfolio risk gate | Verify: pytest risk tests | Gate: portfolio 风控可阻止 Agent 过度交易。 | Parallelizable: No
[x] TP-07.03 | P1 | 实现 paper kill switch 和异常行情熔断 | Verify: risk and service tests | Gate: paper loop 可被安全暂停。 | Parallelizable: No
[x] TP-08.01 | P2 | 定义 public/private 执行边界 | Verify: docs review + security scan | Gate: 边界不会误导 Agent 在 public repo 真实交易。 | Parallelizable: No
[x] TP-08.02 | P2 | 设计 audited intent handoff | Verify: schema draft review | Gate: 未来实盘层有清晰契约但不污染 public repo。 | Parallelizable: No
[x] TP-08.03 | P2 | 加固 public repo guardrails | Verify: bash scripts/security-scan.sh && bash scripts/supply-chain-audit.sh | Gate: public repo 可长期保持公开安全。 | Parallelizable: No

说明：
- 每一行后续必须绑定 `TP-XX(.YY...)`
- 不允许出现无归属 TODO
