# Stability Hardening Task Tree

This is the current `auto-tasks` repair plan for moving TradeCat from early
release stability toward mature CLI/TUI software robustness.

Machine-readable source: `references/stability-hardening-task-tree.json`.

This repository keeps the Skill root clean and explicitly forbids root
`assets/`, so this task tree is stored under `references/` instead of the
default `assets/tasks/` container.

## Task Context

- Status: `In Progress` for release delivery; implementation leaves are landed.
- Source verdict: `WARN`, no current `BLOCK`.
- Baseline release: `v0.1.2`
- Debug Evidence Contract: `Required` for `TP-01` and `TP-02` because they touch
  runtime networking and local state integrity; optional for governance-only
  leaves unless CI, installer, or runtime failures appear during execution.

## Completion Evidence

- Runtime hardening landed in `project/src/tradecat_terminal/`:
  `sheets.py`, `state.py`, `cache.py`, `settings.py`, `migrations.py`,
  `diagnostics.py`, `lifecycle.py`, `cli.py`, `structured_cache.py`, and `tui.py`.
- Dependency and installer hardening landed in `project/constraints.txt`,
  `project/install.sh`, `project/install.ps1`, and
  `scripts/bootstrap-dev.sh`.
- CI/canary hardening landed in `.github/workflows/ci.yml`.
- Governance and public docs were updated in `AGENTS.md`, `lessons.md`,
  `project/AGENTS.md`, `project/DEBUG.md`, project README, and
  the relevant `references/` contracts.
- Local verification passed: `bash project/scripts/verify.sh`.
- Deferred from this code-landing pass: commit/tag/GitHub Actions observation and
  release publication, because this turn was scoped to code implementation.

## Source Findings

| Priority | Gap | Evidence | Mature Target |
| --- | --- | --- | --- |
| P1 | Remote fetch has no retry, jitter, or error classification. | `project/src/tradecat_terminal/sheets.py:9` | HTTP transport with bounded retry/backoff/jitter and typed errors. |
| P1 | Local cache/settings writes lack process-level locking. | `project/src/tradecat_terminal/cache.py:176` | Cross-platform file locks and transactional local state updates. |
| P1 | Settings writes are not atomic and corrupt JSON is silently ignored. | `project/src/tradecat_terminal/settings.py:32`, `settings.py:43` | Atomic write, `.bak`, corrupt-file diagnostics, and repair path. |
| P2 | Dependencies are range-based, not locked. | `project/pyproject.toml:16` | `uv.lock` or constraints with drift checks and release evidence. |
| P2 | Installer can bootstrap uv from a remote script. | `project/install.sh:52` | Fixed version/checksum or explicit opt-in. |
| P2 | Public smoke depends on real Google Sheets/network. | `.github/workflows/ci.yml:160` | Keep real smoke, add retry/artifacts and scheduled canary. |
| P2 | Doctor lacks a support bundle. | `project/src/tradecat_terminal/lifecycle.py:15` | `doctor --verbose --bundle --repair` with safe diagnostics. |
| P2 | Cache schema has versions but no migration framework. | `project/src/tradecat_terminal/cache.py:128` | Explicit migrations, backup, rollback, fixtures. |
| P3 | Permanent snapshots lack disk-waterline warnings. | `project/src/tradecat_terminal/cache.py:224` | Doctor cache-size warnings and prune guidance. |
| P3 | CI only fixes Python at 3.12. | `.github/workflows/ci.yml:16` | Python 3.12/3.13 and broader shell/terminal smoke. |

## Scope

In scope:

- Network transport resilience, retry/backoff/jitter, and typed error surfaces.
- Cache/settings locking, atomicity, corrupt-file preservation, and concurrent
  write tests.
- Dependency locking, installer supply-chain hardening, SBOM/audit evidence.
- Doctor observability, support bundle, cache disk-waterline diagnostics.
- Cache schema migration framework.
- CI canary, retry artifacts, Python 3.13, and shell/terminal smoke expansion.
- Documentation, release gate, and closeout updates.

Out of scope:

- Trading logic, new data sources, or dataset business semantics.
- Root layout changes or root `assets/` creation.
- Replacing the TUI framework.
- Server-side services, databases, or production process management.

## Task Package Tree

```text
- ROOT
  ├─ TP-01 [branch] [P0] 远端 IO 韧性与错误语义
  │  ├─ TP-01.01 [leaf] [P0] 抽象远端 CSV transport
  │  ├─ TP-01.02 [leaf] [P0] 实现 retry/backoff/jitter 策略
  │  ├─ TP-01.03 [leaf] [P0] 定义可消费错误分类
  │  ├─ TP-01.04 [leaf] [P0] 贯通 sync/probe/TUI/installer 错误输出
  │  └─ TP-01.05 [leaf] [P0] 远端 IO 回归与文档
  ├─ TP-02 [branch] [P0] 本地状态一致性与并发安全
  │  ├─ TP-02.01 [leaf] [P0] 确定文件锁与事务边界
  │  ├─ TP-02.02 [leaf] [P0] 缓存写入加锁并保持原子投影
  │  ├─ TP-02.03 [leaf] [P0] settings 原子写与损坏备份
  │  └─ TP-02.04 [leaf] [P0] 并发与恢复回归测试
  ├─ TP-03 [branch] [P1] 依赖可复现与供应链边界
  │  ├─ TP-03.01 [leaf] [P1] 建立依赖 lock/constraints 策略
  │  ├─ TP-03.02 [leaf] [P1] 让 installer 消费锁定依赖
  │  ├─ TP-03.03 [leaf] [P1] 硬化 uv bootstrap
  │  └─ TP-03.04 [leaf] [P1] 补 SBOM 与供应链审计证据
  ├─ TP-04 [branch] [P1] doctor 可观测性与支持包
  │  ├─ TP-04.01 [leaf] [P1] 记录最近错误 ledger
  │  ├─ TP-04.02 [leaf] [P1] 实现 doctor verbose/bundle
  │  ├─ TP-04.03 [leaf] [P1] 缓存磁盘水位与 prune 建议
  │  └─ TP-04.04 [leaf] [P1] doctor 文档与回归
  ├─ TP-05 [branch] [P1] 缓存 schema 迁移框架
  │  ├─ TP-05.01 [leaf] [P1] 定义迁移契约与版本矩阵
  │  ├─ TP-05.02 [leaf] [P1] 实现迁移 runner 与备份回滚
  │  ├─ TP-05.03 [leaf] [P1] 补旧版本 fixture 回归
  │  └─ TP-05.04 [leaf] [P1] doctor 集成迁移状态
  ├─ TP-06 [branch] [P1] CI 与发布韧性扩展
  │  ├─ TP-06.01 [leaf] [P1] 公网 smoke 增加有限 retry 与 artifact
  │  ├─ TP-06.02 [leaf] [P1] 新增 scheduled canary
  │  ├─ TP-06.03 [leaf] [P2] 扩展 Python 版本矩阵
  │  ├─ TP-06.04 [leaf] [P2] 补 shell/terminal smoke 覆盖
  │  └─ TP-06.05 [leaf] [P2] CI 文档与 release gate 对齐
  └─ TP-07 [branch] [P1] 集成交付与发布闭环
     ├─ TP-07.01 [leaf] [P1] 同步项目文档与治理记忆
     ├─ TP-07.02 [leaf] [P1] 完整本地验证与安全扫描
     ├─ TP-07.03 [leaf] [P1] 提交、tag 与 GitHub Actions 观察
     └─ TP-07.04 [leaf] [P2] closeout 与经验归档
```

## Execution Waves

- Wave 1: `TP-01.01`, `TP-02.01`, `TP-03.01`, `TP-03.03`, `TP-05.01`, `TP-06.03`
- Wave 2: `TP-01.02`, `TP-01.03`, `TP-02.02`, `TP-02.03`, `TP-03.02`, `TP-06.04`
- Wave 3: `TP-01.04`, `TP-02.04`, `TP-03.04`, `TP-04.01`, `TP-05.02`, `TP-06.01`
- Wave 4: `TP-01.05`, `TP-04.02`, `TP-05.03`, `TP-06.02`
- Wave 5: `TP-04.03`, `TP-05.04`, `TP-06.05`
- Wave 6: `TP-04.04`
- Wave 7: `TP-07.01`
- Wave 8: `TP-07.02`
- Wave 9: `TP-07.03`
- Wave 10: `TP-07.04`

## Next Executable Leaves

- `TP-01.01`: 抽象远端 CSV transport。
- `TP-02.01`: 确定文件锁与事务边界。
- `TP-03.01`: 建立依赖 lock/constraints 策略。
- `TP-03.03`: 硬化 uv bootstrap。
- `TP-05.01`: 定义迁移契约与版本矩阵。
- `TP-06.03`: 扩展 Python 版本矩阵。

## Leaf Task Details

| ID | Priority | Depends On | Parallel | Objective | Verify | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| `TP-01.01` | P0 | - | No | 在 sheets 层引入最小 transport 边界，优先采用成熟 HTTP 客户端或 urllib3/httpx retry 能力，保留现有 fetch_csv_body 调用面。 | 单元测试能 monkeypatch transport，不访问真实网络即可覆盖成功、超时、HTTP 错误、DNS 错误。 | 业务层仍调用 fetch_csv_body/fetch_csv_rows；网络实现细节只存在于 transport 层。 |
| `TP-01.02` | P0 | `TP-01.01` | No | 为临时性网络失败增加有限重试、指数退避和抖动，并保持总耗时受 timeout/attempts 控制。 | 测试证明 timeout、HTTP 429/5xx、连接重置会重试；HTTP 4xx 业务错误不盲目重试；最大等待时间受控。 | 默认同步不会因为一次瞬时失败直接失败，也不会无限阻塞 TUI 或 installer。 |
| `TP-01.03` | P0 | `TP-01.01` | Yes | 把 DNS、connect timeout、read timeout、HTTP status、CSV decode/parse 等错误分类成稳定 code/message/hint。 | CLI JSON 输出和 doctor payload 包含 error.code、error.kind、retryable、hint；人类文本仍简洁。 | 上层不再依赖 str(exc) 猜错误语义。 |
| `TP-01.04` | P0 | `TP-01.02`, `TP-01.03` | No | 让 sync、probe、doctor、TUI 状态栏和 installer fallback 消费统一错误分类，输出对应修复建议。 | 模拟每类错误时，doctor/TUI/installer 展示不同 hint；缓存命中时网络失败不清空旧数据。 | 用户能判断是弱网、远端拒绝、数据格式漂移还是本地缓存问题。 |
| `TP-01.05` | P0 | `TP-01.04` | No | 补齐远端 IO 单元测试、CI smoke 说明和 first-run/cache 文档，防止网络层退化。 | pytest 覆盖 retry、error classification、TUI hint、doctor JSON；references/first-run-cache.md 与 quality-gate 同步。 | 网络韧性变成测试和文档契约，不只是实现细节。 |
| `TP-02.01` | P0 | - | No | 选择成熟 filelock/portalocker 等跨平台锁方案，定义 cache dataset 锁、全局 manifest 锁、settings 锁和超时策略。 | 设计文档列出每个写路径使用的 lock 文件、超时、失败返回和 stale lock 策略。 | 禁止各模块自行发明不同锁语义。 |
| `TP-02.02` | P0 | `TP-02.01` | No | 把 write_dataset_body、manifest、latest.json/jsonl/csv、root manifest 纳入锁保护和可恢复写入序列。 | 并发启动两个 sync/probe 进程后，manifest、latest 和 stream_events 都保持合法 JSON/CSV 且无丢字段。 | 任一 dataset 写入失败不会留下半更新的 latest/manifest 组合。 |
| `TP-02.03` | P0 | `TP-02.01` | Yes | 将 save_settings 改为 lock + tmp replace + .bak；load_settings 遇到损坏 JSON 时保留坏文件并返回可诊断 warning。 | 构造损坏 settings.json 后 doctor 能报告 corrupt_settings 并保留原文件；set/unset 并发执行后 JSON 合法。 | 配置损坏不再静默变成空配置。 |
| `TP-02.04` | P0 | `TP-02.02`, `TP-02.03` | No | 补充多进程/多线程写缓存、写 settings、stale lock、写入中断恢复测试。 | pytest 新增并发用例；必要时用 subprocess 模拟真实进程；连续运行不 flaky。 | 本地状态一致性有可重复回归证据。 |
| `TP-03.01` | P1 | - | No | 选择 uv.lock 或 constraints.txt 作为单一依赖锁定方案，并定义应用于本地、CI、installer 的规则。 | 全新环境安装使用锁定依赖；CI 可验证 lock 与 pyproject 未漂移。 | 同一 tag 在不同时间安装得到同一主依赖集合。 |
| `TP-03.02` | P1 | `TP-03.01` | No | 调整 POSIX/PowerShell installer，在不牺牲简单安装的前提下优先使用 lock/constraints 安装项目依赖。 | 本地 installer smoke 输出版本与 lock 一致；Windows/Unix CI smoke 均通过。 | 用户安装路径与开发/CI 依赖口径一致。 |
| `TP-03.03` | P1 | - | Yes | 为 uv 自动安装增加明确 opt-in、固定版本/校验或强提示，避免用户不知情执行远程安装脚本。 | 无 Python 时 installer 输出明确风险说明；配置开关与 README 文档一致；CI 覆盖跳过/允许两种路径。 | 供应链边界由用户可见配置控制，不是静默远程执行。 |
| `TP-03.04` | P1 | `TP-03.01`, `TP-03.02`, `TP-03.03` | No | 生成或记录依赖清单、pip-audit 结果和 lock 校验结果，作为 release gate 的可审计证据。 | CI 输出 lock/audit/SBOM 或等价 artifact；release notes 能引用结果。 | 发布时能回答本版本实际安装了什么依赖。 |
| `TP-04.01` | P1 | `TP-01.03` | Yes | 为 sync/probe/installer/TUI 失败写入本地最近错误摘要，包含时间、dataset、error code、retryable、hint。 | 模拟错误后 doctor --json 能读取最近错误；ledger 不包含凭证或完整私密环境变量。 | 用户截图之外也有可诊断的近期失败证据。 |
| `TP-04.02` | P1 | `TP-02.03`, `TP-04.01` | No | 新增 doctor --verbose 与 --bundle，输出版本、平台、Python、install ref、cache summary、settings health、recent errors。 | doctor --bundle 生成公开安全 JSON/zip；secret scan 不报；损坏 settings 和缺失 cache 均有清晰项。 | 支持包能直接用于 issue/CI 排障，不需要用户手工拼信息。 |
| `TP-04.03` | P1 | `TP-04.02` | Yes | 在 doctor 中加入 cache size、dataset size、snapshot count、水位阈值和 prune 建议；默认仍不自动删除。 | 构造大缓存后 doctor 输出 warning 与精确 prune 命令；小缓存不提示。 | 永久快照策略不会无声吃满磁盘。 |
| `TP-04.04` | P1 | `TP-04.02`, `TP-04.03` | No | 更新 README、quality gate、tests，固定 doctor --json/--verbose/--bundle 输出契约。 | pytest 覆盖 bundle schema、脱敏、磁盘水位、repair hints；文档命令可复制。 | doctor 成为可维护的公开诊断契约。 |
| `TP-05.01` | P1 | - | No | 定义 cache schema version、manifest version、latest projection version 的迁移规则、兼容范围和触发时机。 | references/cache-contract.md 增加 migration section；旧版本读写策略明确。 | 后续 schema 变更不能靠临时 if/else 隐式处理。 |
| `TP-05.02` | P1 | `TP-02.02`, `TP-05.01` | No | 新增 migrations 模块，在 cache 写入/doctor repair 前检测版本，先备份再迁移，失败可回滚。 | 从旧 manifest fixture 迁移到当前版本；失败时备份保留且 cache 不被破坏。 | 迁移过程受锁保护且可重复执行。 |
| `TP-05.03` | P1 | `TP-05.02` | Yes | 保存最小旧版本 cache fixtures，覆盖空缓存、snapshot dataset、stream dataset、损坏 manifest 等迁移路径。 | pytest 使用 fixtures 验证迁移结果、备份文件、幂等性和错误报告。 | cache schema 迭代有真实历史样本保护。 |
| `TP-05.04` | P1 | `TP-04.02`, `TP-05.03` | No | 让 doctor 显示 cache migration status，并在 repair 模式下可显式执行迁移。 | doctor --json 展示 migration.current/needed/backup；doctor --repair 能执行迁移并输出结果。 | 用户能安全完成缓存升级，不需要手动删目录。 |
| `TP-06.01` | P1 | `TP-01.02` | Yes | 为 published-install-smoke 增加有限重试、状态 JSON artifact 和失败诊断日志，同时不隐藏最终失败。 | 模拟首次失败二次成功时 CI step 成功并上传诊断；连续失败时保留 artifact 并失败。 | 真实公网 gate 既不脆弱，也不变成永远通过。 |
| `TP-06.02` | P1 | `TP-06.01` | No | 增加定时或 workflow_dispatch canary，跑固定 release raw 安装、sync、plain TUI，区分代码回归和外部服务波动。 | GitHub Actions 可手动触发 canary；失败输出 release ref、dataset 状态和错误分类。 | 发布后公网健康不只在 push 时被观察。 |
| `TP-06.03` | P2 | - | Yes | 在合适 job 中增加 Python 3.13 覆盖，保留 3.12 作为最低支持版本。 | 3.12 与 3.13 的 install/lint/test/wheel 基础 gate 均通过；不扩大公网 smoke 成本。 | 提前发现新 Python 版本兼容性问题。 |
| `TP-06.04` | P2 | `TP-06.03` | Yes | 补充 POSIX sh、bash、PowerShell、plain TUI、非交互终端、PATH 未生效场景的 smoke。 | CI 至少覆盖 Unix shell installer、PowerShell installer、plain TUI、status JSON 和 uninstall。 | 常见终端入口不会只靠人工发现问题。 |
| `TP-06.05` | P2 | `TP-06.01`, `TP-06.02`, `TP-06.03`, `TP-06.04` | No | 更新 quality-gate、release 文档和 README，说明哪些 gate 是 deterministic，哪些 gate 是 canary。 | references/quality-gate.md 可解释 push CI、tag CI、scheduled canary、manual canary 的不同责任。 | CI 失败时能快速判断是代码门禁、发布门禁还是外部健康探针。 |
| `TP-07.01` | P1 | `TP-01.05`, `TP-02.04`, `TP-03.04`, `TP-04.04`, `TP-05.04`, `TP-06.05` | No | 更新 README、AGENTS、DEBUG、references、lessons，记录新稳定性契约和操作口径。 | references/index.md 能导航新增稳定性契约；AGENTS/README/quality-gate 口径一致。 | 架构/契约变更没有文档滞后。 |
| `TP-07.02` | P1 | `TP-07.01` | No | 执行根 verify、Skill strict、root guard、security scan、supply-chain audit、remote data contract 和 installer smoke。 | 所有本地 gate 返回零；git status 不含运行态目录；失败项必须有 DEBUG 记录。 | 本地证据足够进入 commit/push/release。 |
| `TP-07.03` | P1 | `TP-07.02` | No | 按主题提交硬化改动，推送 develop，创建下一稳定 tag，观察 develop/tag CI，并更新 GitHub Release 正文。 | develop 与 tag CI 均成功；Release body 含精确 run IDs、安装命令和 rollback。 | 交付物可从远端复现，不停留在本地成功。 |
| `TP-07.04` | P2 | `TP-07.03` | No | 把本任务树状态、执行证据、剩余风险和经验写入 references/archive 与 lessons，便于后续审计。 | 任务树 JSON/Markdown 更新为完成状态或明确剩余项；references/index.md 可定位归档。 | 稳定性硬化闭环有长期可追溯证据。 |

## Dependency Graph

```text
TP-01.01 -> TP-01.02
TP-01.01 -> TP-01.03
TP-01.02 -> TP-01.04
TP-01.03 -> TP-01.04
TP-01.04 -> TP-01.05
TP-02.01 -> TP-02.02
TP-02.01 -> TP-02.03
TP-02.02 -> TP-02.04
TP-02.03 -> TP-02.04
TP-03.01 -> TP-03.02
TP-03.01 -> TP-03.04
TP-03.02 -> TP-03.04
TP-03.03 -> TP-03.04
TP-01.03 -> TP-04.01
TP-02.03 -> TP-04.02
TP-04.01 -> TP-04.02
TP-04.02 -> TP-04.03
TP-04.02 -> TP-04.04
TP-04.03 -> TP-04.04
TP-02.02 -> TP-05.02
TP-05.01 -> TP-05.02
TP-05.02 -> TP-05.03
TP-04.02 -> TP-05.04
TP-05.03 -> TP-05.04
TP-01.02 -> TP-06.01
TP-06.01 -> TP-06.02
TP-06.03 -> TP-06.04
TP-06.01 -> TP-06.05
TP-06.02 -> TP-06.05
TP-06.03 -> TP-06.05
TP-06.04 -> TP-06.05
TP-01.05 -> TP-07.01
TP-02.04 -> TP-07.01
TP-03.04 -> TP-07.01
TP-04.04 -> TP-07.01
TP-05.04 -> TP-07.01
TP-06.05 -> TP-07.01
TP-07.01 -> TP-07.02
TP-07.02 -> TP-07.03
TP-07.03 -> TP-07.04
```

## Global Acceptance

- Remote CSV fetching has bounded retry, jitter, typed errors, and deterministic tests.
- Cache, structured latest files, root manifest, and settings writes are protected by cross-platform locks and atomic updates.
- Corrupt settings/cache metadata are preserved and surfaced through doctor instead of silently ignored.
- Dependency installation is reproducible for local, CI, and installer paths.
- Installer supply-chain behavior is explicit, documented, and covered by smoke tests.
- Doctor can produce a public-safe support bundle and disk-waterline warnings.
- Cache schema migration is explicit, backed up, rollbackable, and fixture-tested.
- CI distinguishes deterministic gates from live canaries and covers Python 3.12/3.13 plus key shell/terminal paths.
- Documentation, release notes, and governance memory match the implemented behavior.

## Validation Plan

Run after implementation:

```bash
bash scripts/validate-skill.sh --strict
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
PYTHONPATH=project/src project/.venv/bin/python project/scripts/validate_data_contract.py --remote --timeout 10
git diff --check
git status --short --branch --ignored
```

Release/canary validation:

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/<next-tag>/project/install.sh | sh
tradecat doctor --json
tradecat doctor --verbose
tradecat doctor --bundle
tradecat sync-all --timeout 10
tradecat tui event_stream --plain --limit 3
```

## Execution Policy

- Execute Wave 1 first; do not start `TP-07`.
- Keep each leaf commit scoped to its package unless the change is inherently cross-cutting.
- For `TP-01` and `TP-02`, maintain `project/DEBUG.md` while debugging failures.
- After each wave, run the minimum relevant tests plus `bash scripts/verify.sh`.
- Before release, run the full validation plan and observe develop/tag CI.
