# Repo Evidence
- git status 显示 develop ahead 13，且存在未提交的 src/tradecat_auto 与 tests 补丁，以及未跟踪 agent_trade_thesis.py。
- AGENTS.md 明确根目录是 Skill 外壳，仓库根是唯一 Python 项目根，根目录禁止第二份 Skill shell。
- agents/manifest.json 已声明 agent_market_context、agent_trade_thesis、automation service、runtime paths 和错误码。
- src/tradecat_auto 已有 context-audit/run-context、paper ledger、audit journal、health report 和 start-auto-paper。
- health-report 显示 auto-paper 当前 heartbeat_stale，ledger 有历史 paper open positions，安全字段仍为 false。

# Constraints Matrix
- 不得读取任何 Binance credential，不得签名，不得真实下单。
- 不得把 root Skill shell 改成 Python 项目根。
- 任务文档落在 tasks/，避免违反根目录禁止 assets/ 的治理边界。
- 执行实现时必须保持最小改动，不混入无关重构。
- 任何后台 loop 启动必须由用户单独授权；本任务树本身只定义和规划。

# Change Boundary
- 允许新增 tasks/0001-autonomous-agent-trader-loop/ 任务文档和机器任务包。
- 允许最小更新 AGENTS.md 记录 tasks/ 目录职责。
- 本轮不修改交易行为、不启动服务、不写 runtime、不提交、不 push。

# Risk Matrix
- Agent loop 如果边界不清，会把 research/paper 和真实交易权限混在一起。
- observe-only 与 paper execution 如果共用 runtime writer，可能产生重复下单或重复 ledger 写入。
- 没有 portfolio 风控前，Agent 自主 paper loop 容易不断开新仓或长期持有无 exit plan 仓位。
- 把任务目录放错 root assets/ 会破坏 Skill 包治理约束。

# Assumptions and Falsification
- 当前任务只要求制作落地任务包，不要求本轮直接实现 P1-P7 代码。
- tasks/ 是本仓适配 auto-tasks 的项目内任务目录。
- Hermes 负责市场研究与工具调用，Codex loop 负责工程迭代与任务推进，不直接交易。
- 未来私有 executor 可消费 public repo 产出的 audited intent，但不会反向把凭证写回 public repo。

# Critical Ambiguities
- 真钱 executor 的目标交易所权限、部署方式和人工审批策略尚未定义；因此 P7 只做边界设计。
- Hermes loop 的具体工具调用运行时接口可能依赖本机 Hermes 能力；P2 先以 contract 和 observe-only CLI 固化，不绑定不可复现私有状态。

# Debug Evidence Contract
- 调试模式: Optional
- 若任务属于 bugfix / regression / flaky / crash / CI-only failure，必须切到 `Required`
- `Required` 时必须在当前任务目录创建并维护 `DEBUG.md`
- `DEBUG.md` 必须覆盖复现、观察、假设、实验、根因、修复、回归证据

# Task Package Context Map
## TP-01
- Step Key: `p0_stabilize_baseline`
- 标题: P0 收口当前工程状态
- 类型: `package`
- 目标: 把当前未提交的 Agent trade thesis / paper pipeline 补丁收敛成可验证、可继续开发的稳定基线。
- 父节点: `ROOT`
- 子节点: TP-01.01, TP-01.02, TP-01.03, TP-01.04
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-01.01
- Step Key: `p0_01_preflight`
- 标题: 确认工作树与运行态
- 类型: `action`
- 目标: 记录 git status、HEAD、未提交文件、auto-paper status、health-report 和当前 ledger 摘要。
- 父节点: `TP-01`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: 当前工程状态说明；运行态是否 active 的证据
- 风险: 无
- 备注: 无

### TP-01.02
- Step Key: `p0_02_track_thesis_helper`
- 标题: 收口 agent_trade_thesis helper
- 类型: `action`
- 目标: 把 agent_trade_thesis.py 纳入项目实现边界，并确认 CLI/service/pipeline 对 thesis 的读取、校验、sizing、exit plan 链路一致。
- 父节点: `TP-01`
- 子节点: 无
- 依赖步骤 Key: p0_01_preflight
- 依赖节点 ID: TP-01.01
- 输入: 无
- 输出: 可追踪的 agent_trade_thesis 实现；失败路径 agent_trade_thesis_load_failed
- 风险: 无
- 备注: 无

### TP-01.03
- Step Key: `p0_03_validate_safety`
- 标题: 验证 paper/watch 安全边界
- 类型: `action`
- 目标: 确认新增 thesis 路径不会读取 key、不会签名、不会调用真实账户/订单接口，不会发明默认 sizing/exits。
- 父节点: `TP-01`
- 子节点: 无
- 依赖步骤 Key: p0_02_track_thesis_helper
- 依赖节点 ID: TP-01.02
- 输入: 无
- 输出: 安全验证证据；fail-closed 测试覆盖
- 风险: 无
- 备注: 无

### TP-01.04
- Step Key: `p0_04_checkpoint_ready`
- 标题: 形成 P0 交付证据
- 类型: `action`
- 目标: 整理 P0 改动、验证命令、剩余风险和是否需要本地 checkpoint commit 的判断。
- 父节点: `TP-01`
- 子节点: 无
- 依赖步骤 Key: p0_03_validate_safety
- 依赖节点 ID: TP-01.03
- 输入: 无
- 输出: P0 closeout 摘要；可提交或可继续迭代的基线状态
- 风险: 无
- 备注: 无

## TP-02
- Step Key: `p1_research_loop_contract`
- 标题: P1 定义 Autonomous Research Loop 契约
- 类型: `package`
- 目标: 把 Agent 自主研究循环定义为机器契约、fixture、validator 和文档，而不是先实现复杂运行器。
- 父节点: `ROOT`
- 子节点: TP-02.01, TP-02.02, TP-02.03, TP-02.04
- 依赖步骤 Key: p0_stabilize_baseline
- 依赖节点 ID: TP-01
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-02.01
- Step Key: `p1_01_schema`
- 标题: 设计 agent_research_cycle.v1 schema
- 类型: `action`
- 目标: 定义信号输入、requested market data、tool call provenance、market context、trade thesis、risk notes 和 next action 的稳定 JSON Schema。
- 父节点: `TP-02`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: contracts/tradecat-auto-agent-research-cycle.schema.json
- 风险: 无
- 备注: 无

### TP-02.02
- Step Key: `p1_02_fixtures`
- 标题: 补 research cycle fixtures
- 类型: `action`
- 目标: 提供成功、缺 sizing、缺 exit plan、工具失败、危险 endpoint 被拒绝等 fixture。
- 父节点: `TP-02`
- 子节点: 无
- 依赖步骤 Key: p1_01_schema
- 依赖节点 ID: TP-02.01
- 输入: 无
- 输出: tests/fixtures/agent_research_cycle/*.json
- 风险: 无
- 备注: 无

### TP-02.03
- Step Key: `p1_03_validator`
- 标题: 实现 research cycle validator
- 类型: `action`
- 目标: 新增最小 validator，校验 schema、provenance、安全字段、public-readonly endpoint family 和 fail-closed 规则。
- 父节点: `TP-02`
- 子节点: 无
- 依赖步骤 Key: p1_02_fixtures
- 依赖节点 ID: TP-02.02
- 输入: 无
- 输出: validator/helper；pytest 覆盖
- 风险: 无
- 备注: 无

### TP-02.04
- Step Key: `p1_04_docs_manifest`
- 标题: 更新 Agent 文档和 manifest 索引
- 类型: `action`
- 目标: 把 research cycle 契约加入 agents/manifest.json、SKILL/references 指南和项目文档，文档只引用机器契约。
- 父节点: `TP-02`
- 子节点: 无
- 依赖步骤 Key: p1_03_validator
- 依赖节点 ID: TP-02.03
- 输入: 无
- 输出: manifest important_paths/commands；Hermes Agent 使用说明
- 风险: 无
- 备注: 无

## TP-03
- Step Key: `p2_observe_only_loop`
- 标题: P2 实现 observe-only Agent loop
- 类型: `package`
- 目标: 实现只观察和产出报告的 Agent 研究循环，不写 ledger、不启动 run-loop、不产生 paper order/fill。
- 父节点: `ROOT`
- 子节点: TP-03.01, TP-03.02, TP-03.03, TP-03.04
- 依赖步骤 Key: p1_research_loop_contract
- 依赖节点 ID: TP-02
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-03.01
- Step Key: `p2_01_loop_cli`
- 标题: 新增 observe-only loop 入口
- 类型: `action`
- 目标: 提供本地 CLI/脚本入口，读取最新信号并生成 research task skeleton。
- 父节点: `TP-03`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: observe-only CLI；schema 化输出
- 风险: 无
- 备注: 无

### TP-03.02
- Step Key: `p2_02_tool_plan`
- 标题: 固化 Binance public-readonly 工具编排
- 类型: `action`
- 目标: 定义从信号到 K 线、盘口、资金费率、OI、多空比等 public 数据请求的顺序、降级和错误码。
- 父节点: `TP-03`
- 子节点: 无
- 依赖步骤 Key: p2_01_loop_cli
- 依赖节点 ID: TP-03.01
- 输入: 无
- 输出: tool orchestration policy；endpoint family mapping
- 风险: 无
- 备注: 无

### TP-03.03
- Step Key: `p2_03_outputs`
- 标题: 生成 context/thesis 草案输出
- 类型: `action`
- 目标: observe-only loop 写出 agent_market_context 和 agent_trade_thesis 草案到隔离输出目录。
- 父节点: `TP-03`
- 子节点: 无
- 依赖步骤 Key: p2_02_tool_plan
- 依赖节点 ID: TP-03.02
- 输入: 无
- 输出: agent_market_context.json；agent_trade_thesis.json；research_cycle.json
- 风险: 无
- 备注: 无

### TP-03.04
- Step Key: `p2_04_audit_smoke`
- 标题: 串接 context-audit 但不执行 paper
- 类型: `action`
- 目标: 在 observe-only loop 末尾运行 context-audit 或生成可运行命令，不进入 run-context。
- 父节点: `TP-03`
- 子节点: 无
- 依赖步骤 Key: p2_03_outputs
- 依赖节点 ID: TP-03.03
- 输入: 无
- 输出: audit report；observe-only smoke evidence
- 风险: 无
- 备注: 无

## TP-04
- Step Key: `p3_paper_execution_loop`
- 标题: P3 接入 paper execution loop
- 类型: `package`
- 目标: 让 audit 通过的 Agent thesis 驱动 paper/watch，而不是 CLI 默认参数驱动。
- 父节点: `ROOT`
- 子节点: TP-04.01, TP-04.02, TP-04.03, TP-04.04
- 依赖步骤 Key: p2_observe_only_loop
- 依赖节点 ID: TP-03
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-04.01
- Step Key: `p3_01_audit_gate`
- 标题: 实现 audit -> paper gate
- 类型: `action`
- 目标: 只有 context-audit ok 且 thesis 明确 sizing/leverage/exit plan 时，才允许进入 paper execution。
- 父节点: `TP-04`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: audit gate；拒绝路径测试
- 风险: 无
- 备注: 无

### TP-04.02
- Step Key: `p3_02_thesis_execution`
- 标题: 执行 thesis-driven paper run
- 类型: `action`
- 目标: 把 thesis.paper_intent、exit plan、并发持仓授权完整传递到 paper broker 和 ledger。
- 父节点: `TP-04`
- 子节点: 无
- 依赖步骤 Key: p3_01_audit_gate
- 依赖节点 ID: TP-04.01
- 输入: 无
- 输出: paper execution report；paper ledger position fields
- 风险: 无
- 备注: 无

### TP-04.03
- Step Key: `p3_03_journal_health`
- 标题: 接入 ledger/journal/health
- 类型: `action`
- 目标: 确保 paper execution 写入 ledger、audit journal、cycle archive 后可由 health/daily/replay 读取。
- 父节点: `TP-04`
- 子节点: 无
- 依赖步骤 Key: p3_02_thesis_execution
- 依赖节点 ID: TP-04.02
- 输入: 无
- 输出: audit journal record；health report；daily report
- 风险: 无
- 备注: 无

### TP-04.04
- Step Key: `p3_04_service_mode`
- 标题: 定义连续 paper 服务模式
- 类型: `action`
- 目标: 明确 Hermes loop 如何触发 paper/watch，一次一轮还是后台 run-loop，并加入状态/锁/重复事件保护。
- 父节点: `TP-04`
- 子节点: 无
- 依赖步骤 Key: p3_03_journal_health
- 依赖节点 ID: TP-04.03
- 输入: 无
- 输出: service mode contract；runtime lock policy
- 风险: 无
- 备注: 无

## TP-05
- Step Key: `p4_position_management`
- 标题: P4 持续仓位管理智能
- 类型: `package`
- 目标: 让 Agent 每轮先读取本地 paper account state，再决定 hold/close/adjust/new thesis。
- 父节点: `ROOT`
- 子节点: TP-05.01, TP-05.02, TP-05.03
- 依赖步骤 Key: p3_paper_execution_loop
- 依赖节点 ID: TP-04
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-05.01
- Step Key: `p4_01_account_state`
- 标题: 标准化 paper account state 输入
- 类型: `action`
- 目标: 把本地 paper ledger 派生状态作为 Agent 仓位管理输入，明确不是 Binance 账户状态。
- 父节点: `TP-05`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: paper_account_state contract usage
- 风险: 无
- 备注: 无

### TP-05.02
- Step Key: `p4_02_position_thesis_schema`
- 标题: 定义 position_management_thesis.v1
- 类型: `action`
- 目标: 支持 hold、close intent、adjust exit、add/reduce paper intent 等仓位管理动作。
- 父节点: `TP-05`
- 子节点: 无
- 依赖步骤 Key: p4_01_account_state
- 依赖节点 ID: TP-05.01
- 输入: 无
- 输出: position management schema；fixtures
- 风险: 无
- 备注: 无

### TP-05.03
- Step Key: `p4_03_apply_position_actions`
- 标题: 实现 paper 仓位动作应用层
- 类型: `action`
- 目标: 在 paper ledger 中应用明确授权的 close/adjust 操作，保持默认不改仓。
- 父节点: `TP-05`
- 子节点: 无
- 依赖步骤 Key: p4_02_position_thesis_schema
- 依赖节点 ID: TP-05.02
- 输入: 无
- 输出: paper position action reports；ledger 更新
- 风险: 无
- 备注: 无

## TP-06
- Step Key: `p5_replay_review`
- 标题: P5 回测与复盘闭环
- 类型: `package`
- 目标: 把每轮 context/thesis/execution/ledger 做成可重放 decision trace 和质量报告。
- 父节点: `ROOT`
- 子节点: TP-06.01, TP-06.02, TP-06.03
- 依赖步骤 Key: p3_paper_execution_loop
- 依赖节点 ID: TP-04
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-06.01
- Step Key: `p5_01_trace`
- 标题: 统一 decision trace
- 类型: `action`
- 目标: 把 research_cycle、context audit、pipeline report、ledger delta、risk decision 串成同一 run_id trace。
- 父节点: `TP-06`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: decision trace contract
- 风险: 无
- 备注: 无

### TP-06.02
- Step Key: `p5_02_quality_report`
- 标题: 生成 decision quality report
- 类型: `action`
- 目标: 按机会发现、拒绝原因、仓位结果、Agent 输入完整度统计质量指标。
- 父节点: `TP-06`
- 子节点: 无
- 依赖步骤 Key: p5_01_trace
- 依赖节点 ID: TP-06.01
- 输入: 无
- 输出: decision quality report
- 风险: 无
- 备注: 无

### TP-06.03
- Step Key: `p5_03_replay_determinism`
- 标题: 验证 replay 可复现
- 类型: `action`
- 目标: 确保给定 archive/ledger/fixtures 可以重放出相同 decision trace。
- 父节点: `TP-06`
- 子节点: 无
- 依赖步骤 Key: p5_02_quality_report
- 依赖节点 ID: TP-06.02
- 输入: 无
- 输出: replay determinism tests
- 风险: 无
- 备注: 无

## TP-07
- Step Key: `p6_portfolio_risk`
- 标题: P6 生产级 paper 风控
- 类型: `package`
- 目标: 把 contract 风控升级为 portfolio 级 paper 风控，但仍不进入真实交易。
- 父节点: `ROOT`
- 子节点: TP-07.01, TP-07.02, TP-07.03
- 依赖步骤 Key: p4_position_management
- 依赖节点 ID: TP-05
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-07.01
- Step Key: `p6_01_risk_policy_schema`
- 标题: 定义 portfolio risk policy
- 类型: `action`
- 目标: 新增最大日亏、最大回撤、最大持仓数、单币最大风险、冷却期、置信度门槛等 policy 字段。
- 父节点: `TP-07`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: risk policy schema/contract
- 风险: 无
- 备注: 无

### TP-07.02
- Step Key: `p6_02_risk_engine`
- 标题: 实现 portfolio risk gate
- 类型: `action`
- 目标: 按 policy 对新开仓、加仓、减仓、关闭和持仓维持进行 paper risk decision。
- 父节点: `TP-07`
- 子节点: 无
- 依赖步骤 Key: p6_01_risk_policy_schema
- 依赖节点 ID: TP-07.01
- 输入: 无
- 输出: risk_decision.v1 reason coverage
- 风险: 无
- 备注: 无

### TP-07.03
- Step Key: `p6_03_kill_switch`
- 标题: 实现 paper kill switch 和异常行情熔断
- 类型: `action`
- 目标: 提供本地只读/配置型 kill switch、异常波动暂停和冷却期拒绝。
- 父节点: `TP-07`
- 子节点: 无
- 依赖步骤 Key: p6_02_risk_engine
- 依赖节点 ID: TP-07.02
- 输入: 无
- 输出: kill switch policy；cooldown rejection
- 风险: 无
- 备注: 无

## TP-08
- Step Key: `p7_private_executor_design`
- 标题: P7 私有实盘 executor 设计
- 类型: `package`
- 目标: 只设计未来私有 executor 与 public TradeCat 的边界，不在 public repo 实现真实交易。
- 父节点: `ROOT`
- 子节点: TP-08.01, TP-08.02, TP-08.03
- 依赖步骤 Key: p6_portfolio_risk
- 依赖节点 ID: TP-07
- 输入: 无
- 输出: 无
- 风险: 无
- 备注: 无

### TP-08.01
- Step Key: `p7_01_boundary_doc`
- 标题: 定义 public/private 执行边界
- 类型: `action`
- 目标: 写清 public repo 输出 audited intent，private executor 才能读取 key、签名和处理真实订单。
- 父节点: `TP-08`
- 子节点: 无
- 依赖步骤 Key: 无
- 依赖节点 ID: 无
- 输入: 无
- 输出: executor boundary design
- 风险: 无
- 备注: 无

### TP-08.02
- Step Key: `p7_02_intent_handshake`
- 标题: 设计 audited intent handoff
- 类型: `action`
- 目标: 定义 public paper/watch intent 如何被私有 executor 消费、审批、拒绝和回传执行摘要。
- 父节点: `TP-08`
- 子节点: 无
- 依赖步骤 Key: p7_01_boundary_doc
- 依赖节点 ID: TP-08.01
- 输入: 无
- 输出: intent handoff schema draft
- 风险: 无
- 备注: 无

### TP-08.03
- Step Key: `p7_03_public_guardrails`
- 标题: 加固 public repo guardrails
- 类型: `action`
- 目标: 添加或加强测试/扫描，确保 public repo 不会引入真实交易能力。
- 父节点: `TP-08`
- 子节点: 无
- 依赖步骤 Key: p7_02_intent_handshake
- 依赖节点 ID: TP-08.02
- 输入: 无
- 输出: security guard tests；supply-chain scan coverage
- 风险: 无
- 备注: 无
