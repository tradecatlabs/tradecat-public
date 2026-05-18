# Lessons

## 2026-05-18 Retired UI Must Not Block The Agent Trader Shape

- 现象：用户目标已经转向 Agent 交易员常驻纸面交易，但仓库仍保留大量 TUI、安装器、cache-browser、analysis facts 文档和门禁，导致工程重心偏离。
- 本质：旧产品面会变成组织惯性；当目标形态改变时，留下“可运行但不再核心”的入口会持续消耗维护预算并误导 Agent。
- 规则：TradeCat Public 当前只保留公开信号源、Agent context/thesis contract、paper/watch、ledger、risk、reports、monitor 和验证门禁；TUI/install/cache-browser 不再是默认产品面。
- 防复发：guard、manifest、README、AGENTS、Skill references 和 CI 必须同时禁止退役路径复活。
- 验证：每次架构变动都运行 `bash scripts/guard_public_local_files.sh`、`bash scripts/agent-smoke.sh`、`bash scripts/verify.sh` 和 `bash scripts/validate-skill.sh --strict`。

## 2026-05-08 Agent Consumption Needs A Machine Contract, Not More Prose

- 现象：仓库已经是 Skill 结构，但 Hermes/Agent 仍需要先读长文档、猜命令副作用、猜 JSON 形状和失败退出码。
- 本质：面向人的 README 不能替代面向机器的 contract；Agent 最依赖的是可机读 manifest、稳定 schema、退出码和风险分类。
- 规则：新增 Agent 入口时，先更新 `agents/manifest.json`，再更新平台 profile；profile 只能指向 manifest，不能复制第二份真相。
- 防复发：所有广告给 Agent 解析的 JSON 必须带 `schema/schema_version`；失败必须是 object error；非交互失败必须返回非 0。
- 验证：每次改 CLI JSON、request.py、wrapper、manifest 或 references，都必须跑 `bash scripts/agent-smoke.sh` 和 `pytest tests/test_*contract*.py tests/test_exit_codes.py`。

## 2026-05-08 Stable Error Objects Must Also Be Semantically Correct

- 现象：`sync` 曾把任意 `ValueError` 都包装成 `invalid_dataset_key`，导致 `TRADECAT_CACHE_COMPRESSION=bad` 被误报成 dataset_key 错。
- 本质：有稳定 JSON envelope 不等于 contract 正确；错误分类必须保留真实失败域，否则 Agent 会沿错误修复路径继续误操作。
- 规则：dataset 缺失必须使用专用异常；配置错误、参数错误、远端错误、本地运行时错误必须拆分成不同 `error.code/kind/hint`。
- 防复发：CLI 捕获异常时禁止用宽泛 `ValueError` 直接映射为业务特定错误码。
- 验证：新增错误分类时必须覆盖“非 dataset ValueError 不得返回 invalid_dataset_key”和“未知 runtime exception 返回稳定 JSON error”。

## 2026-05-08 First-run Cache Must Be A Product Contract

- 现象：`tradecat` 启动后显示 `cache=empty-cache`、`remote=-`、`fetched=-`，后台 probe 在弱网下超时。
- 本质：安装、缓存、TUI 三层没有把“首次公开数据快照”当成同一个产品契约；安装期允许跳过或失败，TUI 又是 cache-first，于是空缓存被用户感知成程序坏了。
- 规则：默认入口必须尽量保证默认 tap 有缓存；如果做不到，界面必须明确说清是 cold start、正在 warming、需要 sync，不能只暴露内部状态码。
- 防复发：安装脚本在 `sync-all` 失败后必须兜底同步 `event_stream`；TUI 状态栏必须区分 `warming / sync-needed / probe-failed`；doctor 必须给出 `sync-all` 和弱网 timeout 修复命令。
- 验证：每次改安装、缓存、TUI 启动逻辑，都要覆盖空缓存、首次探针失败、弱网 timeout 和默认 dataset 可用性。

## 2026-05-08 Public Install Must Exercise The Real First-Run Path

- 现象：CI 的公网 raw installer smoke 曾设置 `TRADECAT_INSTALL_SKIP_SYNC=1`，只能证明脚本可下载、launcher 可执行，不能证明普通用户安装后首屏有缓存。
- 本质：测试为了稳定性绕开了产品契约，导致“安装成功”和“首次可用”被拆成两件事。
- 规则：发布通道的公网安装 smoke 必须走普通用户路径；如初次同步失败，可以显式执行 `doctor --sync` 做一次修复，但最终必须断言默认 `event_stream` 为 `ready`。
- 防复发：稳定安装默认指向 tag；开发分支自动更新必须通过 `TRADECAT_INSTALL_BRANCH=develop` 显式选择；tag 内 release 文档使用稳定工作流查询链接，避免发布后再改 tag 文档。
- 验证：每次改 installer、CI 或 release 口径，都要同时检查 raw install、cache warm、release notes、README 默认命令和本地裸环境 verify。

## 2026-05-08 Local State Needs One Durable Write Boundary

- 现象：网络失败、并发 sync/probe、settings 损坏和 schema 演进原本分散在多个模块里处理，成熟度审查时暴露出长期风险。
- 本质：本地状态是产品数据面，不能靠各模块临时 `write_text` / `replace` / `str(exc)` 维持正确性；需要统一边界约束时间、并发、错误语义和迁移。
- 规则：远端错误必须 typed；本地写入必须 filelock + atomic replace；用户配置必须 `.bak`；metadata schema 必须有 migrations；doctor 必须能产出 public-safe support bundle。
- 防复发：新增运行态模块时先判断是否属于状态边界；属于则复用 `state.py`、`diagnostics.py`、`migrations.py`，禁止复制私有锁和私有错误格式。
- 验证：每次改 cache/settings/sync/doctor，必须覆盖 typed error、corrupt file、migration status、support bundle 和 root verify。

## 2026-05-18 Autonomous Paper Trader Must Be Resident When Requested

- 现象：自主纸面交易任务完成后只做了实现和验证，`auto-paper` 服务没有常驻运行，状态为 `not_running`。
- 本质：工程交付和运行交付是两件事；如果用户目标是 autonomous trader，纸面 run-loop 停止就等于目标未进入运行态。
- 规则：当任务目标明确包含“持续纸面交易 / autonomous paper trader / 常驻 loop”时，`paper_service_not_running` 必须作为阻塞状态处理，不能在汇报中当作普通信息略过。
- 防复发：交付前必须检查 `bash scripts/start-auto-paper.sh status --json` 和 `tradecat auto health-report --json`；若需要常驻，应由 operator/Hermes 明确执行 `start` 或 systemd/timer keepalive，并持续检查 heartbeat。
- 验证：常驻目标的验收必须包含 `running=true`、heartbeat 未 stale、`real_orders=false`、`signed_requests=false`、`reads_api_keys=false`，且所有运行态只在 gitignored `.runtime/auto-paper/`。
