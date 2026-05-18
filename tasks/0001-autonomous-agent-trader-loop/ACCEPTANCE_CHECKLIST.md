# Acceptance Checklist

# Global Standards
- [ ] public-read-only + paper/watch 是公开仓库不可突破的硬边界。
- [ ] 机器契约优先，文档只能引用主契约，不制造第二真相源。
- [ ] 运行态只允许写入 gitignored .runtime/.tradecat 或任务明确指定的本地隔离目录。
- [ ] 所有任务可由 TP-XX 叶子节点追踪到验证证据和回滚边界。

# Task Package Checklists
## TP-01
- 标题: P0 收口当前工程状态
- 验收项:
  - [ ] 达成 `P0 收口当前工程状态` 的 objective，且输出物可复核
- Verify: git diff --check；PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py；bash scripts/verify.sh
- Gate: 当前补丁可解释、验证通过、auto-paper 当前运行状态清楚，且未引入真实交易能力。
- 输出物:
  - [ ] 把当前未提交的 Agent trade thesis / paper pipeline 补丁收敛成可验证、可继续开发的稳定基线。
- 标准清单:
  - [ ] Verify: git diff --check；PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py；bash scripts/verify.sh
  - [ ] Gate: 当前补丁可解释、验证通过、auto-paper 当前运行状态清楚，且未引入真实交易能力。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-01.01
- 标题: 确认工作树与运行态
- 验收项:
  - [ ] 不启动服务，不写 runtime。
  - [ ] 明确当前 dirty files 是否属于待收口补丁。
- Verify: git status --short --branch；bash scripts/start-auto-paper.sh status --json；PYTHONPATH=src python3 -m tradecat_auto.cli health-report --json
- Gate: 状态证据足够支持后续补丁或提交决策。
- 输出物:
  - [ ] 当前工程状态说明
  - [ ] 运行态是否 active 的证据
- 标准清单:
  - [ ] Verify: git status --short --branch；bash scripts/start-auto-paper.sh status --json；PYTHONPATH=src python3 -m tradecat_auto.cli health-report --json
  - [ ] Gate: 状态证据足够支持后续补丁或提交决策。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-01.02
- 标题: 收口 agent_trade_thesis helper
- 验收项:
  - [ ] 缺文件、坏 JSON、坏 schema 时 fail-closed。
  - [ ] CLI override > thesis.paper_intent > missing 的优先级保持稳定。
- Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_service.py
- Gate: agent_trade_thesis 不再是漂移的未定义输入面。
- 输出物:
  - [ ] 可追踪的 agent_trade_thesis 实现
  - [ ] 失败路径 agent_trade_thesis_load_failed
- 标准清单:
  - [ ] Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_service.py
  - [ ] Gate: agent_trade_thesis 不再是漂移的未定义输入面。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-01.03
- 标题: 验证 paper/watch 安全边界
- 验收项:
  - [ ] real_orders/signed_requests/reads_api_keys 全部为 false。
  - [ ] 无 thesis 或 thesis 缺 sizing 时继续 agent_sizing_required。
- Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py
- Gate: 安全字段与拒绝行为符合公开仓库边界。
- 输出物:
  - [ ] 安全验证证据
  - [ ] fail-closed 测试覆盖
- 标准清单:
  - [ ] Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py
  - [ ] Gate: 安全字段与拒绝行为符合公开仓库边界。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-01.04
- 标题: 形成 P0 交付证据
- 验收项:
  - [ ] bash scripts/verify.sh 通过。
  - [ ] git status 中改动边界清楚。
- Verify: bash scripts/verify.sh && git diff --check && git status --short --branch
- Gate: P0 可作为 P1 契约设计的稳定起点。
- 输出物:
  - [ ] P0 closeout 摘要
  - [ ] 可提交或可继续迭代的基线状态
- 标准清单:
  - [ ] Verify: bash scripts/verify.sh && git diff --check && git status --short --branch
  - [ ] Gate: P0 可作为 P1 契约设计的稳定起点。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

## TP-02
- 标题: P1 定义 Autonomous Research Loop 契约
- 验收项:
  - [ ] 达成 `P1 定义 Autonomous Research Loop 契约` 的 objective，且输出物可复核
- Verify: 确认子节点范围、依赖与状态闭环
- Gate: 前置步骤已完成: p0_stabilize_baseline
- 输出物:
  - [ ] 把 Agent 自主研究循环定义为机器契约、fixture、validator 和文档，而不是先实现复杂运行器。
- 标准清单:
  - [ ] Verify: 确认子节点范围、依赖与状态闭环
  - [ ] Gate: 前置步骤已完成: p0_stabilize_baseline
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-02.01
- 标题: 设计 agent_research_cycle.v1 schema
- 验收项:
  - [ ] schema_version 固定 1.0.0。
  - [ ] 包含 error_code、provenance、safety。
  - [ ] 明确 observe_only、paper_candidate、reject 三类 next_action。
- Verify: schema fixture validation test
- Gate: 契约足以表达一轮 Agent 自主研究，不含真实交易执行字段。
- 输出物:
  - [ ] contracts/tradecat-auto-agent-research-cycle.schema.json
- 标准清单:
  - [ ] Verify: schema fixture validation test
  - [ ] Gate: 契约足以表达一轮 Agent 自主研究，不含真实交易执行字段。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-02.02
- 标题: 补 research cycle fixtures
- 验收项:
  - [ ] 每个 fixture 都可说明期望 error_code 或 next_action。
  - [ ] 危险 fixture 不包含真实凭证值，只包含 synthetic credential-like 字段。
- Verify: pytest contract fixture tests
- Gate: fixture 能覆盖后续 loop 的核心行为。
- 输出物:
  - [ ] tests/fixtures/agent_research_cycle/*.json
- 标准清单:
  - [ ] Verify: pytest contract fixture tests
  - [ ] Gate: fixture 能覆盖后续 loop 的核心行为。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检
  - [ ] 维护 `DEBUG.md` 并保留回归证据

### TP-02.03
- 标题: 实现 research cycle validator
- 验收项:
  - [ ] signed/account/order/private endpoint 必须拒绝。
  - [ ] 缺 sizing/exits 时不得自动补默认值。
- Verify: PYTHONPATH=src python3 -m pytest tests/test_agent_research_cycle.py
- Gate: research cycle 可作为 Agent loop 的单一输入输出契约。
- 输出物:
  - [ ] validator/helper
  - [ ] pytest 覆盖
- 标准清单:
  - [ ] Verify: PYTHONPATH=src python3 -m pytest tests/test_agent_research_cycle.py
  - [ ] Gate: research cycle 可作为 Agent loop 的单一输入输出契约。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-02.04
- 标题: 更新 Agent 文档和 manifest 索引
- 验收项:
  - [ ] 不制造第二真相源。
  - [ ] 明确 observe-only 是第一落地点。
- Verify: bash scripts/validate-skill.sh --strict
- Gate: Agent/Hermes 能从 Skill 包理解 research loop 契约。
- 输出物:
  - [ ] manifest important_paths/commands
  - [ ] Hermes Agent 使用说明
- 标准清单:
  - [ ] Verify: bash scripts/validate-skill.sh --strict
  - [ ] Gate: Agent/Hermes 能从 Skill 包理解 research loop 契约。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

## TP-03
- 标题: P2 实现 observe-only Agent loop
- 验收项:
  - [ ] 达成 `P2 实现 observe-only Agent loop` 的 objective，且输出物可复核
- Verify: 确认子节点范围、依赖与状态闭环
- Gate: 前置步骤已完成: p1_research_loop_contract
- 输出物:
  - [ ] 实现只观察和产出报告的 Agent 研究循环，不写 ledger、不启动 run-loop、不产生 paper order/fill。
- 标准清单:
  - [ ] Verify: 确认子节点范围、依赖与状态闭环
  - [ ] Gate: 前置步骤已完成: p1_research_loop_contract
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-03.01
- 标题: 新增 observe-only loop 入口
- 验收项:
  - [ ] 默认只读，不写 paper ledger。
  - [ ] 输出包含 signal provenance 和 requested market data plan。
- Verify: 定向 pytest + CLI smoke
- Gate: 可以稳定生成一轮研究任务。
- 输出物:
  - [ ] observe-only CLI
  - [ ] schema 化输出
- 标准清单:
  - [ ] Verify: 定向 pytest + CLI smoke
  - [ ] Gate: 可以稳定生成一轮研究任务。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-03.02
- 标题: 固化 Binance public-readonly 工具编排
- 验收项:
  - [ ] 只允许 allowlist public/read-only GET market endpoints。
  - [ ] 工具失败可降级为 WATCH_ONLY，不得硬开 paper。
- Verify: context-audit fixture tests
- Gate: Agent 工具调用顺序可审计、可复现。
- 输出物:
  - [ ] tool orchestration policy
  - [ ] endpoint family mapping
- 标准清单:
  - [ ] Verify: context-audit fixture tests
  - [ ] Gate: Agent 工具调用顺序可审计、可复现。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-03.03
- 标题: 生成 context/thesis 草案输出
- 验收项:
  - [ ] 输出目录不等于 auto-paper ledger runtime。
  - [ ] 无 Agent 明确 sizing/exits 时 next_action 只能是 observe 或 reject。
- Verify: pytest + json schema validation
- Gate: observe-only 产物可被 context-audit 消费。
- 输出物:
  - [ ] agent_market_context.json
  - [ ] agent_trade_thesis.json
  - [ ] research_cycle.json
- 标准清单:
  - [ ] Verify: pytest + json schema validation
  - [ ] Gate: observe-only 产物可被 context-audit 消费。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-03.04
- 标题: 串接 context-audit 但不执行 paper
- 验收项:
  - [ ] 不调用 run-context，不写 paper order/fill。
  - [ ] audit 失败时输出结构化 error_code。
- Verify: bash scripts/agent-smoke.sh 或定向 observe smoke
- Gate: observe-only loop 可以安全接入 Hermes。
- 输出物:
  - [ ] audit report
  - [ ] observe-only smoke evidence
- 标准清单:
  - [ ] Verify: bash scripts/agent-smoke.sh 或定向 observe smoke
  - [ ] Gate: observe-only loop 可以安全接入 Hermes。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

## TP-04
- 标题: P3 接入 paper execution loop
- 验收项:
  - [ ] 达成 `P3 接入 paper execution loop` 的 objective，且输出物可复核
- Verify: 确认子节点范围、依赖与状态闭环
- Gate: 前置步骤已完成: p2_observe_only_loop
- 输出物:
  - [ ] 让 audit 通过的 Agent thesis 驱动 paper/watch，而不是 CLI 默认参数驱动。
- 标准清单:
  - [ ] Verify: 确认子节点范围、依赖与状态闭环
  - [ ] Gate: 前置步骤已完成: p2_observe_only_loop
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-04.01
- 标题: 实现 audit -> paper gate
- 验收项:
  - [ ] 缺 sizing 返回 agent_sizing_required。
  - [ ] 缺 exit plan 不应用默认 TP/SL/time-stop。
- Verify: pytest run-context failure paths
- Gate: paper 开仓只能来自合格 Agent thesis。
- 输出物:
  - [ ] audit gate
  - [ ] 拒绝路径测试
- 标准清单:
  - [ ] Verify: pytest run-context failure paths
  - [ ] Gate: paper 开仓只能来自合格 Agent thesis。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-04.02
- 标题: 执行 thesis-driven paper run
- 验收项:
  - [ ] sizing_source 标识 Agent thesis。
  - [ ] 同币种多仓只有显式授权才允许。
- Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py
- Gate: paper execution 与 Agent thesis 字段一致。
- 输出物:
  - [ ] paper execution report
  - [ ] paper ledger position fields
- 标准清单:
  - [ ] Verify: PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_paper_ledger.py tests/test_service.py
  - [ ] Gate: paper execution 与 Agent thesis 字段一致。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-04.03
- 标题: 接入 ledger/journal/health
- 验收项:
  - [ ] 所有记录可追溯到 research_cycle run_id。
  - [ ] 安全字段保持 false。
- Verify: paper-report/health-report/audit-journal 定向测试
- Gate: paper 运行结果可审计。
- 输出物:
  - [ ] audit journal record
  - [ ] health report
  - [ ] daily report
- 标准清单:
  - [ ] Verify: paper-report/health-report/audit-journal 定向测试
  - [ ] Gate: paper 运行结果可审计。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-04.04
- 标题: 定义连续 paper 服务模式
- 验收项:
  - [ ] 默认不自动启动长期后台服务。
  - [ ] 重复 event_id 不重复开仓。
- Verify: service tests + start-auto-paper status smoke
- Gate: 连续 paper 服务不会和 observe-only 输出互相踩写。
- 输出物:
  - [ ] service mode contract
  - [ ] runtime lock policy
- 标准清单:
  - [ ] Verify: service tests + start-auto-paper status smoke
  - [ ] Gate: 连续 paper 服务不会和 observe-only 输出互相踩写。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

## TP-05
- 标题: P4 持续仓位管理智能
- 验收项:
  - [ ] 达成 `P4 持续仓位管理智能` 的 objective，且输出物可复核
- Verify: 确认子节点范围、依赖与状态闭环
- Gate: 前置步骤已完成: p3_paper_execution_loop
- 输出物:
  - [ ] 让 Agent 每轮先读取本地 paper account state，再决定 hold/close/adjust/new thesis。
- 标准清单:
  - [ ] Verify: 确认子节点范围、依赖与状态闭环
  - [ ] Gate: 前置步骤已完成: p3_paper_execution_loop
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-05.01
- 标题: 标准化 paper account state 输入
- 验收项:
  - [ ] hard_boundaries 明确 real_orders/signed_requests/reads_api_keys/binance_account_state false。
- Verify: paper_account_state tests
- Gate: Agent 不会误把本地 paper 状态当真实账户。
- 输出物:
  - [ ] paper_account_state contract usage
- 标准清单:
  - [ ] Verify: paper_account_state tests
  - [ ] Gate: Agent 不会误把本地 paper 状态当真实账户。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-05.02
- 标题: 定义 position_management_thesis.v1
- 验收项:
  - [ ] 默认动作是 hold/noop。
  - [ ] close/adjust/add/reduce 必须显式、带 reason 和 provenance。
- Verify: schema validation tests
- Gate: 仓位管理 thesis 可被机器审计。
- 输出物:
  - [ ] position management schema
  - [ ] fixtures
- 标准清单:
  - [ ] Verify: schema validation tests
  - [ ] Gate: 仓位管理 thesis 可被机器审计。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-05.03
- 标题: 实现 paper 仓位动作应用层
- 验收项:
  - [ ] 无明确 action 不改仓。
  - [ ] 所有 action 写 audit journal。
- Verify: paper ledger position management tests
- Gate: 持续仓位管理仍是 paper-only。
- 输出物:
  - [ ] paper position action reports
  - [ ] ledger 更新
- 标准清单:
  - [ ] Verify: paper ledger position management tests
  - [ ] Gate: 持续仓位管理仍是 paper-only。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

## TP-06
- 标题: P5 回测与复盘闭环
- 验收项:
  - [ ] 达成 `P5 回测与复盘闭环` 的 objective，且输出物可复核
- Verify: 确认子节点范围、依赖与状态闭环
- Gate: 前置步骤已完成: p3_paper_execution_loop
- 输出物:
  - [ ] 把每轮 context/thesis/execution/ledger 做成可重放 decision trace 和质量报告。
- 标准清单:
  - [ ] Verify: 确认子节点范围、依赖与状态闭环
  - [ ] Gate: 前置步骤已完成: p3_paper_execution_loop
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-06.01
- 标题: 统一 decision trace
- 验收项:
  - [ ] trace 可从 archive/journal 重建。
  - [ ] 每条 trace 有 error_code 聚合。
- Verify: replay trace fixture tests
- Gate: 复盘可解释每次开仓或拒绝。
- 输出物:
  - [ ] decision trace contract
- 标准清单:
  - [ ] Verify: replay trace fixture tests
  - [ ] Gate: 复盘可解释每次开仓或拒绝。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-06.02
- 标题: 生成 decision quality report
- 验收项:
  - [ ] 缺 sizing、缺 exit plan、audit reject、risk reject 可聚合。
  - [ ] 报告不包含投资建议，只做 paper 复盘。
- Verify: quality report tests
- Gate: Codex loop 可用报告推进工程迭代。
- 输出物:
  - [ ] decision quality report
- 标准清单:
  - [ ] Verify: quality report tests
  - [ ] Gate: Codex loop 可用报告推进工程迭代。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-06.03
- 标题: 验证 replay 可复现
- 验收项:
  - [ ] 同输入重放得到稳定 schema/output。
  - [ ] 非确定性时间字段被固定或隔离。
- Verify: pytest replay tests
- Gate: 审计与回测闭环可信。
- 输出物:
  - [ ] replay determinism tests
- 标准清单:
  - [ ] Verify: pytest replay tests
  - [ ] Gate: 审计与回测闭环可信。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检
  - [ ] 维护 `DEBUG.md` 并保留回归证据

## TP-07
- 标题: P6 生产级 paper 风控
- 验收项:
  - [ ] 达成 `P6 生产级 paper 风控` 的 objective，且输出物可复核
- Verify: 确认子节点范围、依赖与状态闭环
- Gate: 前置步骤已完成: p4_position_management
- 输出物:
  - [ ] 把 contract 风控升级为 portfolio 级 paper 风控，但仍不进入真实交易。
- 标准清单:
  - [ ] Verify: 确认子节点范围、依赖与状态闭环
  - [ ] Gate: 前置步骤已完成: p4_position_management
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-07.01
- 标题: 定义 portfolio risk policy
- 验收项:
  - [ ] 默认保守且不发明交易参数。
  - [ ] 每个拒绝 reason 稳定可测试。
- Verify: risk schema tests
- Gate: policy 可由 Agent/operator 明确配置。
- 输出物:
  - [ ] risk policy schema/contract
- 标准清单:
  - [ ] Verify: risk schema tests
  - [ ] Gate: policy 可由 Agent/operator 明确配置。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-07.02
- 标题: 实现 portfolio risk gate
- 验收项:
  - [ ] 超过限制时 fail-closed。
  - [ ] risk_decision 包含 policy snapshot 和 reason。
- Verify: pytest risk tests
- Gate: portfolio 风控可阻止 Agent 过度交易。
- 输出物:
  - [ ] risk_decision.v1 reason coverage
- 标准清单:
  - [ ] Verify: pytest risk tests
  - [ ] Gate: portfolio 风控可阻止 Agent 过度交易。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-07.03
- 标题: 实现 paper kill switch 和异常行情熔断
- 验收项:
  - [ ] kill switch 只影响 paper/watch。
  - [ ] 触发后所有新仓拒绝并有 error_code。
- Verify: risk and service tests
- Gate: paper loop 可被安全暂停。
- 输出物:
  - [ ] kill switch policy
  - [ ] cooldown rejection
- 标准清单:
  - [ ] Verify: risk and service tests
  - [ ] Gate: paper loop 可被安全暂停。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检
  - [ ] 维护 `DEBUG.md` 并保留回归证据

## TP-08
- 标题: P7 私有实盘 executor 设计
- 验收项:
  - [ ] 达成 `P7 私有实盘 executor 设计` 的 objective，且输出物可复核
- Verify: 确认子节点范围、依赖与状态闭环
- Gate: 前置步骤已完成: p6_portfolio_risk
- 输出物:
  - [ ] 只设计未来私有 executor 与 public TradeCat 的边界，不在 public repo 实现真实交易。
- 标准清单:
  - [ ] Verify: 确认子节点范围、依赖与状态闭环
  - [ ] Gate: 前置步骤已完成: p6_portfolio_risk
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-08.01
- 标题: 定义 public/private 执行边界
- 验收项:
  - [ ] public repo 不出现 key、secret、signed endpoint、real order 代码。
  - [ ] 私有 executor 输入必须是 audited intent。
- Verify: docs review + security scan
- Gate: 边界不会误导 Agent 在 public repo 真实交易。
- 输出物:
  - [ ] executor boundary design
- 标准清单:
  - [ ] Verify: docs review + security scan
  - [ ] Gate: 边界不会误导 Agent 在 public repo 真实交易。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-08.02
- 标题: 设计 audited intent handoff
- 验收项:
  - [ ] handoff 不包含凭证。
  - [ ] 私有执行结果回传必须脱敏。
- Verify: schema draft review
- Gate: 未来实盘层有清晰契约但不污染 public repo。
- 输出物:
  - [ ] intent handoff schema draft
- 标准清单:
  - [ ] Verify: schema draft review
  - [ ] Gate: 未来实盘层有清晰契约但不污染 public repo。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检

### TP-08.03
- 标题: 加固 public repo guardrails
- 验收项:
  - [ ] credential-like 字段和 signed/account/order endpoint 被拒绝。
  - [ ] CI/verify 可发现边界回归。
- Verify: bash scripts/security-scan.sh && bash scripts/supply-chain-audit.sh
- Gate: public repo 可长期保持公开安全。
- 输出物:
  - [ ] security guard tests
  - [ ] supply-chain scan coverage
- 标准清单:
  - [ ] Verify: bash scripts/security-scan.sh && bash scripts/supply-chain-audit.sh
  - [ ] Gate: public repo 可长期保持公开安全。
  - [ ] 完成后更新 `STATUS.md` 的 `Recent Evidence`
  - [ ] 交付前完成 REVIEW / SHIP 自检
