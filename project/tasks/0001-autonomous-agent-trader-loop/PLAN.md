# Planning Summary
按 P0-P7 串行推进主链路：先收口当前工程基线，再定义 autonomous research loop 契约，然后落 observe-only，再接入 paper execution，之后扩展持续仓位管理、replay 复盘、portfolio paper 风控，最后只设计私有实盘 executor 边界。
- 编译节点总数: 36
- 叶子执行项: 28
- 执行波次数: 25
- 当前任务必须遵守 `SPEC -> PLAN -> BUILD -> TEST -> REVIEW -> SHIP`

# Lifecycle Gates
- 不得跳过 gate：SPEC、PLAN、BUILD、TEST、REVIEW、SHIP 每一阶段都必须有可审计证据。
- SPEC：每个新增契约先写 schema 和 fixture。
- PLAN：每个实现阶段先明确写入边界和 fail-closed 行为。
- BUILD：只实现当前 ready 叶子节点，不跨阶段偷跑。
- TEST：定向测试先过，再跑项目/Skill/安全门禁。
- REVIEW：检查真实交易边界、runtime 隔离和 provenance 完整性。
- SHIP：每波结束提供 git status、验证命令和剩余风险。

# Simplest Path
先用机器契约和 observe-only loop 固定 Agent 自主研究输入输出，再让 paper execution 消费同一 thesis；避免一开始就实现实盘、复杂编排或后台多进程。

# Split Strategy
顶层 TP 对应 P0-P7；每个顶层包下只保留能独立验证的叶子任务。P0-P3 是必经 MVP，P4-P6 是 paper 自主交易员成熟化，P7 是私有实盘边界设计。

# Execution Waves
- Wave 1: TP-01.01
- Wave 2: TP-01.02
- Wave 3: TP-01.03
- Wave 4: TP-01.04
- Wave 5: TP-02.01
- Wave 6: TP-02.02
- Wave 7: TP-02.03
- Wave 8: TP-02.04
- Wave 9: TP-03.01
- Wave 10: TP-03.02
- Wave 11: TP-03.03
- Wave 12: TP-03.04
- Wave 13: TP-04.01
- Wave 14: TP-04.02
- Wave 15: TP-04.03
- Wave 16: TP-04.04
- Wave 17: TP-05.01, TP-06.01
- Wave 18: TP-05.02, TP-06.02
- Wave 19: TP-05.03, TP-06.03
- Wave 20: TP-07.01
- Wave 21: TP-07.02
- Wave 22: TP-07.03
- Wave 23: TP-08.01
- Wave 24: TP-08.02
- Wave 25: TP-08.03

# Next Executable Leaves
- 无

# Dependency Graph
TP-01.01 -> TP-01.02
TP-01.02 -> TP-01.03
TP-01.03 -> TP-01.04
TP-01.01 -> TP-02.01
TP-01.02 -> TP-02.01
TP-01.03 -> TP-02.01
TP-01.04 -> TP-02.01
TP-01.01 -> TP-02.02
TP-01.02 -> TP-02.02
TP-01.03 -> TP-02.02
TP-01.04 -> TP-02.02
TP-02.01 -> TP-02.02
TP-01.01 -> TP-02.03
TP-01.02 -> TP-02.03
TP-01.03 -> TP-02.03
TP-01.04 -> TP-02.03
TP-02.02 -> TP-02.03
TP-01.01 -> TP-02.04
TP-01.02 -> TP-02.04
TP-01.03 -> TP-02.04
TP-01.04 -> TP-02.04
TP-02.03 -> TP-02.04
TP-02.01 -> TP-03.01
TP-02.02 -> TP-03.01
TP-02.03 -> TP-03.01
TP-02.04 -> TP-03.01
TP-02.01 -> TP-03.02
TP-02.02 -> TP-03.02
TP-02.03 -> TP-03.02
TP-02.04 -> TP-03.02
TP-03.01 -> TP-03.02
TP-02.01 -> TP-03.03
TP-02.02 -> TP-03.03
TP-02.03 -> TP-03.03
TP-02.04 -> TP-03.03
TP-03.02 -> TP-03.03
TP-02.01 -> TP-03.04
TP-02.02 -> TP-03.04
TP-02.03 -> TP-03.04
TP-02.04 -> TP-03.04
TP-03.03 -> TP-03.04
TP-03.01 -> TP-04.01
TP-03.02 -> TP-04.01
TP-03.03 -> TP-04.01
TP-03.04 -> TP-04.01
TP-03.01 -> TP-04.02
TP-03.02 -> TP-04.02
TP-03.03 -> TP-04.02
TP-03.04 -> TP-04.02
TP-04.01 -> TP-04.02
TP-03.01 -> TP-04.03
TP-03.02 -> TP-04.03
TP-03.03 -> TP-04.03
TP-03.04 -> TP-04.03
TP-04.02 -> TP-04.03
TP-03.01 -> TP-04.04
TP-03.02 -> TP-04.04
TP-03.03 -> TP-04.04
TP-03.04 -> TP-04.04
TP-04.03 -> TP-04.04
TP-04.01 -> TP-05.01
TP-04.02 -> TP-05.01
TP-04.03 -> TP-05.01
TP-04.04 -> TP-05.01
TP-04.01 -> TP-05.02
TP-04.02 -> TP-05.02
TP-04.03 -> TP-05.02
TP-04.04 -> TP-05.02
TP-05.01 -> TP-05.02
TP-04.01 -> TP-05.03
TP-04.02 -> TP-05.03
TP-04.03 -> TP-05.03
TP-04.04 -> TP-05.03
TP-05.02 -> TP-05.03
TP-04.01 -> TP-06.01
TP-04.02 -> TP-06.01
TP-04.03 -> TP-06.01
TP-04.04 -> TP-06.01
TP-04.01 -> TP-06.02
TP-04.02 -> TP-06.02
TP-04.03 -> TP-06.02
TP-04.04 -> TP-06.02
TP-06.01 -> TP-06.02
TP-04.01 -> TP-06.03
TP-04.02 -> TP-06.03
TP-04.03 -> TP-06.03
TP-04.04 -> TP-06.03
TP-06.02 -> TP-06.03
TP-05.01 -> TP-07.01
TP-05.02 -> TP-07.01
TP-05.03 -> TP-07.01
TP-05.01 -> TP-07.02
TP-05.02 -> TP-07.02
TP-05.03 -> TP-07.02
TP-07.01 -> TP-07.02
TP-05.01 -> TP-07.03
TP-05.02 -> TP-07.03
TP-05.03 -> TP-07.03
TP-07.02 -> TP-07.03
TP-07.01 -> TP-08.01
TP-07.02 -> TP-08.01
TP-07.03 -> TP-08.01
TP-07.01 -> TP-08.02
TP-07.02 -> TP-08.02
TP-07.03 -> TP-08.02
TP-08.01 -> TP-08.02
TP-07.01 -> TP-08.03
TP-07.02 -> TP-08.03
TP-07.03 -> TP-08.03
TP-08.02 -> TP-08.03

# Rollback Protocol
- 恢复 `INDEX.md` 当前任务行
- 恢复本任务目录到初始化状态
- 不得影响其他任务目录
