# Agent Readiness Remediation Task Tree

This is the `auto-tasks` execution plan for turning `tradecat-public` into a
stable, low-ambiguity, machine-consumable Skill repository for Hermes and other
shell-capable agents.

Machine-readable source: `references/agent-readiness-remediation-task-tree.json`.

This repository keeps the Skill root clean and explicitly forbids root
`assets/`, so this task tree is stored under `references/` instead of the
default `assets/tasks/` container.

## Task Context

- Status: `Implemented locally`.
- Source plan: `.hermes/plans/2026-05-08_173607-agent-readiness-remediation-plan.md`.
- Current baseline: root is a Skill wrapper; Python project lives under
  `scripts/project/`.
- Core finding: the repository has structure, but not yet strict enough
  machine contracts for autonomous Agent use.
- Implementation closeout: exit-code propagation, canonical manifest,
  Hermes/OpenAI adapters, JSON schema/version envelopes, request fallback JSON,
  agent-smoke, CI agent-readiness, formal schema drafts, tests, and docs have
  been landed in the working tree.
- Debug Evidence Contract: `Required` for `TP-01` and `TP-04` because they touch
  observed runtime/process failures; optional for pure manifest/docs leaves
  unless implementation uncovers command failures, CI-only failures, flaky tests,
  or transport regressions.

## Goal

Make a new Agent able to safely complete this order without reading long prose
first:

1. Read `agents/manifest.json`.
2. Run status/datasets/path JSON commands.
3. Inspect data through a documented request path.
4. Diagnose empty cache or weak-network states.
5. Only then run mutating sync/install/uninstall flows.
6. Verify delivery through a dedicated agent-readiness gate.

## Scope

In scope:

- Trustworthy non-interactive process exit codes.
- Canonical machine-readable Agent manifest.
- Hermes/OpenAI thin agent metadata that points to the manifest.
- Versioned JSON output contracts and stable error objects.
- Request path versus main CLI remote-fetch reconciliation.
- `scripts/agent-smoke.sh` and CI `agent-readiness` lane.
- Multi-Agent documentation rewrite and command risk classes.
- Optional formal schema/test split/helper maturity work.
- Closeout, validation, release notes, and lessons updates.

Out of scope:

- Root layout rewrite.
- Root `assets/` or `assets/examples/`.
- Trading business logic or new data sources.
- Database, SQL, or server production-chain coupling.
- Committing local `.hermes/`, `.env`, cache payloads, credentials, or runtime state.

## Task Package Tree

```text
- ROOT
  ├─ TP-01 [branch] [P0] 进程与退出码契约
  │  ├─ TP-01.01 [leaf] [P0] 修正 Python module 退出码传播
  │  ├─ TP-01.02 [leaf] [P0] 审计 CLI 命令返回码矩阵
  │  ├─ TP-01.03 [leaf] [P0] 审计 wrapper 与 launcher 退出码透传
  │  ├─ TP-01.04 [leaf] [P1] 明确 start/watch 长运行语义
  │  └─ TP-01.05 [leaf] [P0] 补齐退出码回归测试
  ├─ TP-02 [branch] [P0] 机器可读 Agent 契约
  │  ├─ TP-02.01 [leaf] [P0] 定义 manifest 字段与风险分类
  │  ├─ TP-02.02 [leaf] [P0] 新增 agents/manifest.json
  │  ├─ TP-02.03 [leaf] [P1] 新增 Hermes 适配元数据并扩展 OpenAI 元数据
  │  ├─ TP-02.04 [leaf] [P0] 撰写 Agent Contract 长文档
  │  └─ TP-02.05 [leaf] [P1] 补齐 Agent 契约测试
  ├─ TP-03 [branch] [P0] 稳定 JSON API 契约
  │  ├─ TP-03.01 [leaf] [P0] 确定 JSON envelope 策略
  │  ├─ TP-03.02 [leaf] [P0] 为 CLI JSON 输出加 schema/version
  │  ├─ TP-03.03 [leaf] [P0] 统一错误对象结构
  │  ├─ TP-03.04 [leaf] [P1] 补齐 request/export/bundle JSON schema
  │  └─ TP-03.05 [leaf] [P0] 补齐 JSON 契约回归测试
  ├─ TP-04 [branch] [P0] 远端取数路径统一
  │  ├─ TP-04.01 [leaf] [P0] 决策共享 transport 或显式双路径
  │  ├─ TP-04.02 [leaf] [P0] 实现或收敛远端 transport 契约
  │  ├─ TP-04.03 [leaf] [P0] 对齐 request.py 和 validate_data_contract
  │  ├─ TP-04.04 [leaf] [P1] 完善冷启动与弱网诊断
  │  └─ TP-04.05 [leaf] [P0] 补齐 transport 回归测试
  ├─ TP-05 [branch] [P1] Agent Smoke 与 CI 门禁
  │  ├─ TP-05.01 [leaf] [P1] 新增 scripts/agent-smoke.sh
  │  ├─ TP-05.02 [leaf] [P1] 整合 Agent 契约测试到项目验证
  │  ├─ TP-05.03 [leaf] [P1] 新增 CI agent-readiness job
  │  ├─ TP-05.04 [leaf] [P2] 失败 artifact 与 canary 分层
  │  └─ TP-05.05 [leaf] [P2] 可选 pre-commit Agent 契约钩子
  ├─ TP-06 [branch] [P1] 多 Agent 文档与治理口径
  │  ├─ TP-06.01 [leaf] [P1] 收敛 SKILL.md 第一跳
  │  ├─ TP-06.02 [leaf] [P1] 更新 README 与 AGENTS 目录/边界
  │  ├─ TP-06.03 [leaf] [P1] 更新 references 导航与架构口径
  │  ├─ TP-06.04 [leaf] [P1] 补充命令风险类与 Fast Path 示例
  │  └─ TP-06.05 [leaf] [P2] 同步 DEBUG/lessons/release 治理记忆
  ├─ TP-07 [branch] [P2] 可维护性成熟升级
  │  ├─ TP-07.01 [leaf] [P2] 拆分大型测试文件
  │  ├─ TP-07.02 [leaf] [P2] 引入 formal JSON Schema 文件
  │  ├─ TP-07.03 [leaf] [P2] 评估顶层 agent helper 脚本
  │  └─ TP-07.04 [leaf] [P2] 评估安全事件日志增强
  └─ TP-08 [branch] [P1] 集成验证与交付闭环
     ├─ TP-08.01 [leaf] [P1] 执行完整本地验证矩阵
     ├─ TP-08.02 [leaf] [P1] 执行代码审查与风险复核
     ├─ TP-08.03 [leaf] [P1] 提交、推送与 CI 观察
     ├─ TP-08.04 [leaf] [P2] 更新发布说明与回滚口径
     └─ TP-08.05 [leaf] [P2] Closeout 与经验归档
```

## Execution Waves

- Wave 1: `TP-01.01`, `TP-02.01`, `TP-03.01`, `TP-04.01`
- Wave 2: `TP-01.02`, `TP-02.02`, `TP-03.02`, `TP-03.03`, `TP-04.02`
- Wave 3: `TP-01.03`, `TP-02.03`, `TP-02.04`, `TP-03.04`, `TP-04.03`, `TP-04.04`
- Wave 4: `TP-01.04`, `TP-02.05`, `TP-03.05`, `TP-04.05`, `TP-06.01`, `TP-06.02`, `TP-07.04`
- Wave 5: `TP-01.05`, `TP-07.02`
- Wave 6: `TP-05.01`, `TP-05.02`
- Wave 7: `TP-05.03`, `TP-05.05`, `TP-06.03`, `TP-07.01`
- Wave 8: `TP-05.04`, `TP-06.04`
- Wave 9: `TP-06.05`, `TP-07.03`
- Wave 10: `TP-08.01`
- Wave 11: `TP-08.02`
- Wave 12: `TP-08.03`
- Wave 13: `TP-08.04`
- Wave 14: `TP-08.05`

## Next Executable Leaves

All P0/P1 implementation leaves have been executed locally. Remaining delivery
work is release/commit/push/CI observation, controlled by `TP-08`.

## Implementation Evidence

- `agents/manifest.json` is the canonical machine contract.
- `agents/hermes.yaml` and `agents/openai.yaml` point to the manifest.
- CLI JSON outputs now include `schema` and `schema_version`.
- Invalid dataset and other validation failures return non-zero with object
  `error`.
- `request.py --format json` returns `tradecat.request_result.v1` success and
  failure payloads while staying standard-library only.
- `scripts/agent-smoke.sh` validates manifest, schemas, readonly fast path, and
  a deliberate non-zero failure.
- `.github/workflows/ci.yml` has an independent `agent-readiness` job.
- Formal schema drafts live under `scripts/project/contracts/`.

Validated locally:

```bash
python3 -m json.tool agents/manifest.json >/dev/null
bash scripts/agent-smoke.sh
bash scripts/validate-skill.sh --strict
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

## Package Summary

| ID | Priority | Objective | Exit Gate |
| --- | --- | --- | --- |
| `TP-01` | P0 | 让 shell exit code 与机器可读失败状态一致。 | 非交互失败不能返回 0。 |
| `TP-02` | P0 | 建立 machine manifest 与 Hermes/OpenAI 薄适配层。 | Agent 只读 manifest 可识别安全入口。 |
| `TP-03` | P0 | 为 Agent 解析的 JSON 输出建立 versioned schema。 | 每个广告 JSON payload 有 schema/version。 |
| `TP-04` | P0 | 统一或显式刻画 request.py 与 CLI 取数行为。 | 不再存在隐藏双真相。 |
| `TP-05` | P1 | 增加 agent-smoke 与 CI agent-readiness lane。 | Agent contract 坏掉时 CI 失败。 |
| `TP-06` | P1 | 文档改成 multi-agent 契约。 | Fast Path 与风险类可从首跳文档找到。 |
| `TP-07` | P2 | 长期测试/schema/helper/日志成熟升级。 | 只在减少真实维护成本时落地。 |
| `TP-08` | P1 | 本地验证、审查、CI、release、closeout 闭环。 | 无本地和远端证据不得发布。 |

## Leaf Task Details

| ID | Priority | Depends On | Parallel | Objective | Verify | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| `TP-01.01` | P0 | - | No | 将 `__main__.py` 改成 `raise SystemExit(main())`。 | `python3 -m tradecat_terminal sync invalid_dataset --json` 退出非 0。 | Python module 入口不能吞掉 `main()` 返回值。 |
| `TP-01.02` | P0 | `TP-01.01` | No | 审计所有 CLI 子命令返回码矩阵。 | 成功、业务失败、参数错误、网络失败、本地异常均有断言。 | 无 `ok=false` 但 exit 0 的非交互失败路径。 |
| `TP-01.03` | P0 | `TP-01.02` | No | 审计 root wrapper、installer launcher、start/watch 退出码透传。 | wrapper 与 module 入口等价失败命令返回码一致。 | wrapper 不掩盖失败。 |
| `TP-01.04` | P1 | `TP-01.03` | Yes | 明确长运行命令是 spawn success 还是 health ready。 | start/watch 对 spawn、health、already-running 给确定状态。 | Agent 不把 fork 成功误判为健康。 |
| `TP-01.05` | P0 | `TP-01.02`, `TP-01.03`, `TP-01.04` | No | 新增退出码回归测试。 | `pytest -q tests/test_exit_codes.py` 通过。 | 退出码回归能在 CI 失败。 |
| `TP-02.01` | P0 | - | Yes | 定义 manifest 字段、风险类、fast path 和 failure modes。 | 草案字段与真实命令/路径一致。 | 字段只表达机器决策必需信息。 |
| `TP-02.02` | P0 | `TP-02.01` | No | 新增 `agents/manifest.json`。 | `python3 -m json.tool agents/manifest.json` 通过。 | 新 Agent 可识别前五个安全命令。 |
| `TP-02.03` | P1 | `TP-02.02` | Yes | 新增 `agents/hermes.yaml` 并扩展 `agents/openai.yaml`。 | YAML 可解析，字段指向 manifest。 | 平台适配不成为第二份真相。 |
| `TP-02.04` | P0 | `TP-02.02` | Yes | 新增 `references/agent-contract.md`。 | `references/index.md` 和 `SKILL.md` 可导航。 | Agent Fast Path 两分钟内可读完。 |
| `TP-02.05` | P1 | `TP-02.02`, `TP-02.03`, `TP-02.04` | No | 新增 Agent 契约测试。 | `pytest -q tests/test_agent_contract.py` 通过。 | manifest/path/profile 失配会失败。 |
| `TP-03.01` | P0 | - | Yes | 确定 JSON envelope 或最小 schema 字段策略。 | 文档记录 breaking change 规则。 | 避免不必要 payload churn。 |
| `TP-03.02` | P0 | `TP-03.01` | No | 为 CLI JSON 输出加 schema/version。 | status/doctor/path/datasets/sync/probe/prune/config JSON 含 schema。 | Agent 不靠命令名猜 payload 类型。 |
| `TP-03.03` | P0 | `TP-03.01` | Yes | 统一 error object。 | 参数错误、非法 dataset、网络失败、本地异常均含稳定 error。 | Agent 不解析 `str(exc)`。 |
| `TP-03.04` | P1 | `TP-03.02`, `TP-03.03` | Yes | 补齐 request/export/bundle JSON schema。 | request/export/bundle 成功失败 payload 均含 schema。 | 数据视图和诊断包使用同一识别方式。 |
| `TP-03.05` | P0 | `TP-03.02`, `TP-03.03`, `TP-03.04` | No | 新增 JSON contract tests。 | `pytest -q tests/test_json_contract.py` 通过。 | schema 漂移必须失败。 |
| `TP-04.01` | P0 | - | No | 决策共享 transport 或显式双路径。 | 文档记录 production/fallback path 与取舍。 | 不存在隐藏双真相。 |
| `TP-04.02` | P0 | `TP-04.01` | No | 实现或收敛远端 transport 契约。 | 成功、timeout、429/5xx、4xx、decode 错误均可离线测。 | fetch 行为集中或可映射。 |
| `TP-04.03` | P0 | `TP-04.02` | No | 对齐 `request.py` 和 `validate_data_contract.py`。 | request 与 remote data contract 在同网络条件下表现一致或差异被标记。 | 差异不靠人工经验理解。 |
| `TP-04.04` | P1 | `TP-03.03`, `TP-04.02` | Yes | 完善 empty cache + weak network 诊断。 | doctor/TUI/CLI JSON 给出 cold-start error、hint、retryable。 | Agent 不把空缓存误判为真空数据。 |
| `TP-04.05` | P0 | `TP-04.02`, `TP-04.03`, `TP-04.04` | No | 新增 transport 回归测试。 | `pytest -q tests/test_transport.py` 通过。 | 网络行为差异必须被测试批准。 |
| `TP-05.01` | P1 | `TP-01.05`, `TP-02.05`, `TP-03.05` | No | 新增 `scripts/agent-smoke.sh`。 | `bash scripts/agent-smoke.sh` 通过；破坏 manifest/exit-code 会失败。 | agent-smoke 独立守住 Agent 契约。 |
| `TP-05.02` | P1 | `TP-01.05`, `TP-02.05`, `TP-03.05`, `TP-04.05` | Yes | 将 contract tests 纳入 verify/CI。 | 根或项目 verify 可运行新增测试。 | 本地和 CI 口径一致。 |
| `TP-05.03` | P1 | `TP-05.01`, `TP-05.02` | No | 新增 CI `agent-readiness` job。 | GitHub Actions 显示独立 job。 | Agent 契约坏掉时 CI 失败。 |
| `TP-05.04` | P2 | `TP-05.03` | Yes | 增加失败 artifacts 与 canary 分层。 | CI 失败上传日志/payload/support bundle。 | CI 失败可诊断。 |
| `TP-05.05` | P2 | `TP-05.01` | Yes | 可选 pre-commit 轻量契约钩子。 | `pre-commit run --all-files` 不过慢。 | 本地钩子不跑 live-network。 |
| `TP-06.01` | P1 | `TP-02.04` | Yes | 收敛 `SKILL.md` 第一跳。 | `bash scripts/validate-skill.sh --strict` 通过。 | 长说明仍在 references。 |
| `TP-06.02` | P1 | `TP-02.03`, `TP-02.04` | Yes | 更新 root/project README/AGENTS 目录和口径。 | 目录树与真实文件一致。 | 文档不再表达为 Codex-only。 |
| `TP-06.03` | P1 | `TP-02.04`, `TP-03.05`, `TP-05.01` | No | 更新 references 导航、架构和 quality gate。 | index 能导航 agent-contract 与任务树。 | 文档门禁与脚本名称一致。 |
| `TP-06.04` | P1 | `TP-06.03` | Yes | 补充 Command Risk Classes 与 Fast Path 示例。 | Fast Path 命令可复制执行。 | 高风险命令不作为默认第一步。 |
| `TP-06.05` | P2 | `TP-06.04` | Yes | 同步 DEBUG、lessons、release 治理记忆。 | secret scan 不报；公开治理文件脱敏。 | 治理记忆可提交。 |
| `TP-07.01` | P2 | `TP-05.02` | Yes | 拆分大型测试文件。 | pytest 全量通过。 | 只调整测试组织，不借机重构生产代码。 |
| `TP-07.02` | P2 | `TP-03.05` | Yes | 引入 formal JSON Schema 文件。 | schema 可校验代表 payload。 | schema 稳定后再引入。 |
| `TP-07.03` | P2 | `TP-05.01`, `TP-06.04` | Yes | 评估顶层 Agent helper。 | 新增则 agent-smoke 覆盖；不新增则记录舍弃原因。 | 不制造第四个入口真相源。 |
| `TP-07.04` | P2 | `TP-04.04` | Yes | 评估安全事件日志增强。 | secret scan 通过，日志有大小/轮转策略。 | 不重复已有 diagnostics。 |
| `TP-08.01` | P1 | `TP-01.05`, `TP-02.05`, `TP-03.05`, `TP-04.05`, `TP-05.04`, `TP-06.05` | No | 执行完整本地验证矩阵。 | 所有本地 gate 返回 0。 | 未通过不得进入远端交付。 |
| `TP-08.02` | P1 | `TP-08.01` | No | 执行代码审查与风险复核。 | 无 BLOCK；WARN 有处理或 deferred reason。 | 不把 P0/P1 合同破损留给 release。 |
| `TP-08.03` | P1 | `TP-08.02` | No | 提交、推送与 CI 观察。 | develop 相关 checks 通过。 | 远端 CI 证据与本地 gate 对齐。 |
| `TP-08.04` | P2 | `TP-08.03` | No | 更新发布说明与回滚口径。 | release 文档含 fixed ref、agent-smoke evidence、rollback。 | 用户和 Agent 理解行为变化。 |
| `TP-08.05` | P2 | `TP-08.04` | No | Closeout 与经验归档。 | 任务树状态和 lessons 更新。 | 交付有可审计 closeout。 |

## PR Split

Recommended implementation split:

1. PR-1: process + machine contract
   - `TP-01`, `TP-02`, first-pass `TP-06.01`/`TP-06.02`.
2. PR-2: JSON contract + transport
   - `TP-03`, `TP-04`, relevant docs.
3. PR-3: CI + docs + closeout
   - `TP-05`, `TP-06`, `TP-08`; add `TP-07` only when it clearly reduces maintenance cost.

## Global Acceptance

- `agents/manifest.json` exists and is the canonical machine contract.
- `agents/hermes.yaml` exists and points to the manifest.
- Every advertised JSON command has a versioned schema name.
- All non-interactive failure paths return non-zero exit code.
- `request.py` and main CLI remote fetch behavior are unified or intentionally
  different with tests and docs.
- `scripts/agent-smoke.sh` exists and CI has an `agent-readiness` job.
- Root/project docs describe the repository as a multi-Agent skill wrapper.
- A fresh Agent can follow manifest + fast path to inspect, validate, consume,
  and diagnose without guessing.

## Validation Plan

Run after implementation:

```bash
python3 -m json.tool agents/manifest.json >/dev/null
bash scripts/agent-smoke.sh
bash scripts/validate-skill.sh --strict
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

Targeted project checks:

```bash
cd scripts/project
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -q -p no:cacheprovider tests/test_exit_codes.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -q -p no:cacheprovider tests/test_json_contract.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -q -p no:cacheprovider tests/test_agent_contract.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -q -p no:cacheprovider tests/test_transport.py
PYTHONPATH=src python3 scripts/validate_data_contract.py --remote --timeout 10
```

## Execution Policy

- Execute Wave 1 first.
- Do not start `TP-08` until all P0/P1 implementation gates are done.
- Keep P2 maturity upgrades optional unless they remove real maintenance cost.
- Maintain `scripts/project/DEBUG.md` while debugging `TP-01` and `TP-04`.
- After each wave, run the smallest relevant targeted tests plus root verify.
- Before release, run the full validation plan and observe GitHub Actions.
