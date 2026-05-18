# Task Overview
- Task ID: `0001`
- Slug: `autonomous-agent-trader-loop`
- Objective: `将 TradeCat 从 Agent-supplied paper/watch 契约层推进为 Hermes/Codex 协作的自主研究与纸面交易员闭环，保持 public-read-only、paper/watch 和真实交易私有层隔离`
- Status: `Done`

## In Scope
- 收口当前未提交的 Agent trade thesis / paper pipeline 补丁为可验证基线。
- 定义 Agent autonomous research loop 的机器契约、fixture、校验和文档。
- 实现 observe-only Agent loop，只生成研究上下文和 thesis，不写 ledger、不开仓。
- 在 audit 通过后把 Agent thesis 接入 paper/watch 执行、ledger、audit journal 和 health report。
- 设计并落地持续 paper 仓位管理、replay 复盘和 portfolio 级 paper 风控。
- 只设计私有实盘 executor 边界，不把真实 key、签名、账户或订单能力放入本公开仓库。

## Out of Scope
- 在 tradecat-public 中读取 Binance key、secret、listen key 或任何真实凭证。
- 调用签名接口、账户接口、订单接口、改杠杆或改保证金端点。
- 真实下单、撤单、实盘仓位管理或真实资金风控实现。
- 把根 Skill 外壳改成 Python 项目根，或在根目录创建 assets/src/tests/pyMakefile。
- 未经过 schema 和 provenance 的自由文本交易执行。

## Task Package Tree
- ROOT
  ├─ TP-01 [branch] [P0] P0 收口当前工程状态
  │  ├─ TP-01.01 [leaf] [P0] 确认工作树与运行态
  │  ├─ TP-01.02 [leaf] [P0] 收口 agent_trade_thesis helper
  │  ├─ TP-01.03 [leaf] [P0] 验证 paper/watch 安全边界
  │  └─ TP-01.04 [leaf] [P0] 形成 P0 交付证据
  ├─ TP-02 [branch] [P0] P1 定义 Autonomous Research Loop 契约
  │  ├─ TP-02.01 [leaf] [P0] 设计 agent_research_cycle.v1 schema
  │  ├─ TP-02.02 [leaf] [P0] 补 research cycle fixtures
  │  ├─ TP-02.03 [leaf] [P0] 实现 research cycle validator
  │  └─ TP-02.04 [leaf] [P1] 更新 Agent 文档和 manifest 索引
  ├─ TP-03 [branch] [P0] P2 实现 observe-only Agent loop
  │  ├─ TP-03.01 [leaf] [P0] 新增 observe-only loop 入口
  │  ├─ TP-03.02 [leaf] [P0] 固化 Binance public-readonly 工具编排
  │  ├─ TP-03.03 [leaf] [P0] 生成 context/thesis 草案输出
  │  └─ TP-03.04 [leaf] [P0] 串接 context-audit 但不执行 paper
  ├─ TP-04 [branch] [P0] P3 接入 paper execution loop
  │  ├─ TP-04.01 [leaf] [P0] 实现 audit -> paper gate
  │  ├─ TP-04.02 [leaf] [P0] 执行 thesis-driven paper run
  │  ├─ TP-04.03 [leaf] [P1] 接入 ledger/journal/health
  │  └─ TP-04.04 [leaf] [P1] 定义连续 paper 服务模式
  ├─ TP-05 [branch] [P1] P4 持续仓位管理智能
  │  ├─ TP-05.01 [leaf] [P1] 标准化 paper account state 输入
  │  ├─ TP-05.02 [leaf] [P1] 定义 position_management_thesis.v1
  │  └─ TP-05.03 [leaf] [P1] 实现 paper 仓位动作应用层
  ├─ TP-06 [branch] [P1] P5 回测与复盘闭环
  │  ├─ TP-06.01 [leaf] [P1] 统一 decision trace
  │  ├─ TP-06.02 [leaf] [P1] 生成 decision quality report
  │  └─ TP-06.03 [leaf] [P1] 验证 replay 可复现
  ├─ TP-07 [branch] [P1] P6 生产级 paper 风控
  │  ├─ TP-07.01 [leaf] [P1] 定义 portfolio risk policy
  │  ├─ TP-07.02 [leaf] [P1] 实现 portfolio risk gate
  │  └─ TP-07.03 [leaf] [P1] 实现 paper kill switch 和异常行情熔断
  └─ TP-08 [branch] [P2] P7 私有实盘 executor 设计
     ├─ TP-08.01 [leaf] [P2] 定义 public/private 执行边界
     ├─ TP-08.02 [leaf] [P2] 设计 audited intent handoff
     └─ TP-08.03 [leaf] [P2] 加固 public repo guardrails

## Requirement Alignment
- 目标: 将 TradeCat 从 Agent-supplied paper/watch 契约层推进为 Hermes/Codex 协作的自主研究与纸面交易员闭环，保持 public-read-only、paper/watch 和真实交易私有层隔离。
- approved plan 顶层步骤数: 8
- 编译后节点总数: 36
- 编译后叶子节点数: 28
- 对齐项: 用户最终目标是让在线表格信号作为输入，由 AI/Agent 自主分析、调用 Binance public/read-only 工具补全市场数据、生成交易 thesis，并驱动 paper/watch 交易与持续仓位管理。
- 对齐项: 当前仓库定位是 Hermes Skill/Agent 契约外壳加内部 Python 项目，适合承载公开安全的 research/paper/watch 契约层。
- 对齐项: 真实交易 executor 必须保留为未来私有层，不能混入 tradecat-public。
- 计划摘要: 按 P0-P7 串行推进主链路：先收口当前工程基线，再定义 autonomous research loop 契约，然后落 observe-only，再接入 paper execution，之后扩展持续仓位管理、replay 复盘、portfolio paper 风控，最后只设计私有实盘 executor 边界。

## Task Package Overview
| Task Package ID | Parent | Depth | Priority | Type | Leaf | Depends On | Wave | Ready | Parallelizable | Objective |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TP-01 | ROOT | 1 | P0 | package | No | - | - | No | No | 把当前未提交的 Agent trade thesis / paper pipeline 补丁收敛成可验证、可继续开发的稳定基线。 |
| TP-01.01 | TP-01 | 2 | P0 | action | Yes | - | 1 | Yes | No | 记录 git status、HEAD、未提交文件、auto-paper status、health-report 和当前 ledger 摘要。 |
| TP-01.02 | TP-01 | 2 | P0 | action | Yes | TP-01.01 | 2 | No | No | 把 agent_trade_thesis.py 纳入项目实现边界，并确认 CLI/service/pipeline 对 thesis 的读取、校验、sizing、exit plan 链路一致。 |
| TP-01.03 | TP-01 | 2 | P0 | action | Yes | TP-01.02 | 3 | No | Yes | 确认新增 thesis 路径不会读取 key、不会签名、不会调用真实账户/订单接口，不会发明默认 sizing/exits。 |
| TP-01.04 | TP-01 | 2 | P0 | action | Yes | TP-01.03 | 4 | No | No | 整理 P0 改动、验证命令、剩余风险和是否需要本地 checkpoint commit 的判断。 |
| TP-02 | ROOT | 1 | P0 | package | No | TP-01.01, TP-01.02, TP-01.03, TP-01.04 | - | No | No | 把 Agent 自主研究循环定义为机器契约、fixture、validator 和文档，而不是先实现复杂运行器。 |
| TP-02.01 | TP-02 | 2 | P0 | action | Yes | TP-01.01, TP-01.02, TP-01.03, TP-01.04 | 5 | No | No | 定义信号输入、requested market data、tool call provenance、market context、trade thesis、risk notes 和 next action 的稳定 JSON Schema。 |
| TP-02.02 | TP-02 | 2 | P0 | action | Yes | TP-01.01, TP-01.02, TP-01.03, TP-01.04, TP-02.01 | 6 | No | No | 提供成功、缺 sizing、缺 exit plan、工具失败、危险 endpoint 被拒绝等 fixture。 |
| TP-02.03 | TP-02 | 2 | P0 | action | Yes | TP-01.01, TP-01.02, TP-01.03, TP-01.04, TP-02.02 | 7 | No | No | 新增最小 validator，校验 schema、provenance、安全字段、public-readonly endpoint family 和 fail-closed 规则。 |
| TP-02.04 | TP-02 | 2 | P1 | action | Yes | TP-01.01, TP-01.02, TP-01.03, TP-01.04, TP-02.03 | 8 | No | No | 把 research cycle 契约加入 agents/manifest.json、SKILL/references 指南和项目文档，文档只引用机器契约。 |
| TP-03 | ROOT | 1 | P0 | package | No | TP-02.01, TP-02.02, TP-02.03, TP-02.04 | - | No | No | 实现只观察和产出报告的 Agent 研究循环，不写 ledger、不启动 run-loop、不产生 paper order/fill。 |
| TP-03.01 | TP-03 | 2 | P0 | action | Yes | TP-02.01, TP-02.02, TP-02.03, TP-02.04 | 9 | No | No | 提供本地 CLI/脚本入口，读取最新信号并生成 research task skeleton。 |
| TP-03.02 | TP-03 | 2 | P0 | action | Yes | TP-02.01, TP-02.02, TP-02.03, TP-02.04, TP-03.01 | 10 | No | No | 定义从信号到 K 线、盘口、资金费率、OI、多空比等 public 数据请求的顺序、降级和错误码。 |
| TP-03.03 | TP-03 | 2 | P0 | action | Yes | TP-02.01, TP-02.02, TP-02.03, TP-02.04, TP-03.02 | 11 | No | No | observe-only loop 写出 agent_market_context 和 agent_trade_thesis 草案到隔离输出目录。 |
| TP-03.04 | TP-03 | 2 | P0 | action | Yes | TP-02.01, TP-02.02, TP-02.03, TP-02.04, TP-03.03 | 12 | No | No | 在 observe-only loop 末尾运行 context-audit 或生成可运行命令，不进入 run-context。 |
| TP-04 | ROOT | 1 | P0 | package | No | TP-03.01, TP-03.02, TP-03.03, TP-03.04 | - | No | No | 让 audit 通过的 Agent thesis 驱动 paper/watch，而不是 CLI 默认参数驱动。 |
| TP-04.01 | TP-04 | 2 | P0 | action | Yes | TP-03.01, TP-03.02, TP-03.03, TP-03.04 | 13 | No | No | 只有 context-audit ok 且 thesis 明确 sizing/leverage/exit plan 时，才允许进入 paper execution。 |
| TP-04.02 | TP-04 | 2 | P0 | action | Yes | TP-03.01, TP-03.02, TP-03.03, TP-03.04, TP-04.01 | 14 | No | No | 把 thesis.paper_intent、exit plan、并发持仓授权完整传递到 paper broker 和 ledger。 |
| TP-04.03 | TP-04 | 2 | P1 | action | Yes | TP-03.01, TP-03.02, TP-03.03, TP-03.04, TP-04.02 | 15 | No | No | 确保 paper execution 写入 ledger、audit journal、cycle archive 后可由 health/daily/replay 读取。 |
| TP-04.04 | TP-04 | 2 | P1 | action | Yes | TP-03.01, TP-03.02, TP-03.03, TP-03.04, TP-04.03 | 16 | No | No | 明确 Hermes loop 如何触发 paper/watch，一次一轮还是后台 run-loop，并加入状态/锁/重复事件保护。 |
| TP-05 | ROOT | 1 | P1 | package | No | TP-04.01, TP-04.02, TP-04.03, TP-04.04 | - | No | No | 让 Agent 每轮先读取本地 paper account state，再决定 hold/close/adjust/new thesis。 |
| TP-05.01 | TP-05 | 2 | P1 | action | Yes | TP-04.01, TP-04.02, TP-04.03, TP-04.04 | 17 | No | No | 把本地 paper ledger 派生状态作为 Agent 仓位管理输入，明确不是 Binance 账户状态。 |
| TP-05.02 | TP-05 | 2 | P1 | action | Yes | TP-04.01, TP-04.02, TP-04.03, TP-04.04, TP-05.01 | 18 | No | No | 支持 hold、close intent、adjust exit、add/reduce paper intent 等仓位管理动作。 |
| TP-05.03 | TP-05 | 2 | P1 | action | Yes | TP-04.01, TP-04.02, TP-04.03, TP-04.04, TP-05.02 | 19 | No | No | 在 paper ledger 中应用明确授权的 close/adjust 操作，保持默认不改仓。 |
| TP-06 | ROOT | 1 | P1 | package | No | TP-04.01, TP-04.02, TP-04.03, TP-04.04 | - | No | Yes | 把每轮 context/thesis/execution/ledger 做成可重放 decision trace 和质量报告。 |
| TP-06.01 | TP-06 | 2 | P1 | action | Yes | TP-04.01, TP-04.02, TP-04.03, TP-04.04 | 17 | No | No | 把 research_cycle、context audit、pipeline report、ledger delta、risk decision 串成同一 run_id trace。 |
| TP-06.02 | TP-06 | 2 | P1 | action | Yes | TP-04.01, TP-04.02, TP-04.03, TP-04.04, TP-06.01 | 18 | No | No | 按机会发现、拒绝原因、仓位结果、Agent 输入完整度统计质量指标。 |
| TP-06.03 | TP-06 | 2 | P1 | action | Yes | TP-04.01, TP-04.02, TP-04.03, TP-04.04, TP-06.02 | 19 | No | No | 确保给定 archive/ledger/fixtures 可以重放出相同 decision trace。 |
| TP-07 | ROOT | 1 | P1 | package | No | TP-05.01, TP-05.02, TP-05.03 | - | No | No | 把 contract 风控升级为 portfolio 级 paper 风控，但仍不进入真实交易。 |
| TP-07.01 | TP-07 | 2 | P1 | action | Yes | TP-05.01, TP-05.02, TP-05.03 | 20 | No | No | 新增最大日亏、最大回撤、最大持仓数、单币最大风险、冷却期、置信度门槛等 policy 字段。 |
| TP-07.02 | TP-07 | 2 | P1 | action | Yes | TP-05.01, TP-05.02, TP-05.03, TP-07.01 | 21 | No | No | 按 policy 对新开仓、加仓、减仓、关闭和持仓维持进行 paper risk decision。 |
| TP-07.03 | TP-07 | 2 | P1 | action | Yes | TP-05.01, TP-05.02, TP-05.03, TP-07.02 | 22 | No | No | 提供本地只读/配置型 kill switch、异常波动暂停和冷却期拒绝。 |
| TP-08 | ROOT | 1 | P2 | package | No | TP-07.01, TP-07.02, TP-07.03 | - | No | Yes | 只设计未来私有 executor 与 public TradeCat 的边界，不在 public repo 实现真实交易。 |
| TP-08.01 | TP-08 | 2 | P2 | action | Yes | TP-07.01, TP-07.02, TP-07.03 | 23 | No | No | 写清 public repo 输出 audited intent，private executor 才能读取 key、签名和处理真实订单。 |
| TP-08.02 | TP-08 | 2 | P2 | action | Yes | TP-07.01, TP-07.02, TP-07.03, TP-08.01 | 24 | No | No | 定义 public paper/watch intent 如何被私有 executor 消费、审批、拒绝和回传执行摘要。 |
| TP-08.03 | TP-08 | 2 | P2 | action | Yes | TP-07.01, TP-07.02, TP-07.03, TP-08.02 | 25 | No | No | 添加或加强测试/扫描，确保 public repo 不会引入真实交易能力。 |

## Reading Order
1. README.md
2. CONTEXT.md
3. PLAN.md
4. ACCEPTANCE.md
5. ACCEPTANCE_CHECKLIST.md
6. TODO.md
7. STATUS.md
