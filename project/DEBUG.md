# TradeCat Terminal Debug Notes

## 当前真相

- 当前仓库根是 Codex Skill 包装层；TradeCat Python 项目根目录是 `project/`。
- 当前服务是用户侧轻量终端：只读 Google Sheets CSV，写本地 JSON 快照缓存。
- 默认入口 `tradecat` 先打开本地缓存 TUI，再在交互循环内按间隔探测远端；禁止启动前阻塞式全量探针。
- 默认永久保留快照；清理只能通过显式 `tradecat prune --apply` 触发，默认 `prune` 只是 dry-run。
- 默认不压缩快照；如需压缩，使用 `TRADECAT_CACHE_COMPRESSION=gzip`，旧纯 JSON 快照仍可读取。
- TUI 不冻结列、不做右侧列滚动；`←/→` 只用于切换 tap，超出屏幕内容按终端宽度裁剪，用户可缩小字体或扩大窗口查看全表。
- TUI 链接支持两类：交易对跳 Binance Futures，URL 文本直接打开 URL。
- Agent/Hermes 机器入口是根目录 `agents/manifest.json`；项目 JSON 输出必须带
  `schema/schema_version`，失败 payload 的 `error` 必须是对象。

## 2026-05-18 auto-paper 常驻但不新增纸面交易

### 现象

- auto-paper loop 常驻运行，paper ledger 持续 mark-to-market，已有 3 个 open paper positions。
- 新增 paper trade 停止，health 降级为 `last_error=remote_http_status`。
- Web 监控显示 Agent thesis/sizing/exits 未配置，信号源为 `source_http_status=404`。

### 根因

- 在线表格 `event_stream` 当前返回 HTTP 404，导致无新信号进入后续链路。
- `.runtime`/`.tradecat` 内没有 Agent 生成的 `agent_trade_thesis` 或 market context JSON。
- 常驻 `start-auto-paper.sh` 之前没有把 Agent thesis 文件路径传入 `run-loop`，即使外部 Agent 写出 thesis 也无法被常驻 loop 消费。

### 修复

- `start-auto-paper.sh` 新增 `TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH`，只在显式配置时传入 `--agent-trade-thesis-path`。
- `tradecat_source`/`service` 保留上游结构化错误码，`SKIPPED_NO_EVENT` 时仍刷新已有 paper positions。
- Web 监控读取最新 cycle archive，显示 `source_http_status`、Agent thesis path 和回撤/告警。
- 保持 fail-closed：没有 Agent sizing/exits 时不发明默认金额、杠杆、止损、止盈。

### 回归

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_auto_service_script.py tests/test_tradecat_source.py tests/test_service.py`
- `bash scripts/verify.sh`
- `bash scripts/validate-skill.sh --strict`
- `bash scripts/security-scan.sh`
- `bash scripts/supply-chain-audit.sh`

## 2026-05-08 Agent/Hermes Readiness Contract

### 现象

- Skill 根结构已经清晰，但 Agent 仍需要阅读长文档才能判断项目根、只读入口、
  会联网命令、会写缓存命令、JSON payload 类型和失败退出码。

### 根因

- `agents/openai.yaml` 太薄，缺少 canonical manifest。
- CLI JSON 输出已有 `--json`，但没有统一 `schema/schema_version`。
- `python -m tradecat_terminal` 入口没有把 `main()` 返回值交给 shell。
- `request.py` 与主 CLI 远端路径的差异没有公开写成 contract。

### 修复

- 新增 `agents/manifest.json` 作为唯一机器主契约，`agents/openai.yaml` 与
  `agents/hermes.yaml` 只作为平台适配层。
- 新增 `contracts.py`，让 CLI 广告 JSON 输出带稳定 schema/version 和 object error。
- 修正 `__main__.py` 为 `raise SystemExit(main())`，并补 `test_exit_codes.py`。
- `request.py --format json` 输出 `tradecat.request_result.v1`，失败也返回 JSON error。
- 新增 `references/agent-contract.md`、`scripts/agent-smoke.sh` 和 CI `agent-readiness` job。
- `UnknownDatasetError` 专门表示 dataset_key 不存在；非 dataset 的 `ValueError`
  不能映射成 `invalid_dataset_key`。

### 回归

- `bash scripts/agent-smoke.sh`
- `PYTHONPATH=src pytest -q tests/test_exit_codes.py tests/test_json_contract.py tests/test_agent_contract.py tests/test_transport.py`

## 禁止回退

- 禁止恢复 SQLite / WAL / SQL query / repair / vacuum / cell store 方案。
- 禁止恢复 `freeze_columns`、固定列冻结、右侧列滚动或智能补空白屏幕逻辑。
- 禁止在 TUI 启动前强制同步全部在线表格。
- 禁止把 `datasets/*/writer.py`、`sources/*` 这类空壳重新作为运行契约入口。

## 历史事故索引

旧 SQLite 持久化、压缩 BLOB、repair/backfill、全量 cell store 等事故记录已归档到：

- `project/DEBUG.archive.md`

该文件只作为历史复盘材料，不是当前运行契约。

## 2026-05-08 稳定性硬化：网络、锁、配置和诊断

### 现象

- 成熟度审查发现远端 CSV 拉取、cache/settings 写入、doctor 诊断、依赖可复现和
  CI canary 仍低于成熟 CLI/TUI 软件水位。

### 根因

- 远端拉取使用单次请求，错误只向上传递字符串，TUI/doctor 无法区分 timeout、
  HTTP、DNS、decode 等类型。
- cache 写入虽然使用同目录 replace，但缺少跨进程锁；settings 写入也没有 `.bak`
  和 corrupt 诊断。
- cache metadata 有 `schema_version`，但缺少显式迁移、备份和 doctor repair 入口。
- 安装依赖依靠范围声明，installer 在无 Python 时可静默执行远程 uv bootstrap。

### 修复

- `sheets.py` 改用 `urllib3` retry/backoff/jitter，并输出 typed error payload。
- `state.py` 集中提供 `filelock` 文件锁和原子写；cache、structured latest、settings
  写入统一走该边界。
- `settings.py` 写入前保留 `settings.json.bak`，损坏配置保留为
  `settings.json.corrupt-*.bak` 并由 doctor 暴露。
- `migrations.py` 增加 cache metadata migration runner，`doctor --repair` 可本地修复。
- `diagnostics.py` 增加 recent error ledger、disk waterline 和 public-safe support bundle。
- Installer 使用 `constraints.txt`，远程 uv bootstrap 改为
  `TRADECAT_INSTALL_ALLOW_UV_BOOTSTRAP=1` 显式授权。
- CI 扩展 Python 3.12/3.13、scheduled/manual canary、public smoke artifact 和 dependency evidence。

### 回归

- `bash project/scripts/verify.sh` 已通过，覆盖 typed remote error、settings corrupt
  recovery、migration repair、doctor bundle 和 disk waterline。

## 2026-05-08 TUI 首屏 empty-cache 与 event_stream 探针超时

### 现象

- 安装入口修复后执行 `tradecat`，TUI 显示 `cache=empty-cache`、`remote=-`、`fetched=-`、`probe=probing`。
- 第二行显示 `timeout=1s fail=1`，说明前台 live probe 已经出现一次失败。

### 根因

- 本机修复安装入口时使用了 `TRADECAT_INSTALL_SKIP_SYNC=1`，因此只有缓存目录骨架，没有首次公开数据快照。
- 空缓存首屏只能依赖 live probe 拉取 Google Sheets。
- 1 秒 `event_stream` 拉取实验三次只有一次成功，另外两次分别在 read 和 TLS handshake 阶段超时。
- 原默认 `interval=1.5s/timeout=1.0s` 对 WSL 弱网链路过于激进，容易先显示空缓存和一次失败。

### 修复

- 本机已执行 `tradecat sync-all` 补齐 4 个 active dataset 缓存。
- 本机配置已写入 `tui_probe_interval.event_stream=3`、`tui_fetch_timeout.event_stream=3`。
- 项目 dataset 契约同步调整为 `event_stream` 前台探针默认 `3s/3s`。
- 安装脚本在 `sync-all` 失败后兜底执行 `tradecat sync event_stream`，优先保证默认入口有数据。
- TUI 状态栏新增 `cold-start=warming/sync-needed/probe-failed`，空缓存不再只是裸状态码。
- `doctor` 对全空缓存新增首次冷启动 warning 和弱网 timeout 修复建议。

### 回归

- `tradecat status --json` 显示 `ready_dataset_count=4`、`missing_dataset_count=0`。
- `tradecat tui event_stream --plain --limit 3` 已直接显示事件流数据。

## 2026-05-08 安装后 tradecat command not found

### 现象

- 用户在 WSL 内执行 `curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/develop/project/install.sh | sh`。
- 安装过程完成源码更新和 editable install 后失败：
  `sh: 129: cannot create /home/lenovo/.local/bin/tradecat: Directory nonexistent`。
- 随后执行 `tradecat` 仍然提示 `command not found`。

### 根因

- 本机 `~/.local/bin/tradecat` 和 `~/.local/bin/tcat` 已存在旧 symlink。
- 旧 symlink 指向已被清理的开发仓库 `.venv/bin/tradecat`，目标父目录不存在。
- POSIX redirection `cat > "$BIN_DIR/tradecat"` 会跟随 symlink 写入目标路径，而不是替换 symlink 本身。
- 因此即使 `mkdir -p "$BIN_DIR"` 已执行，写 launcher 仍会落到已失效的旧目标上并失败。

### 修复

- `install.sh` 写 launcher 改为先写临时文件，再 `rm -f` 旧入口并 `mv` 到目标路径。
- 这样会替换坏 symlink 本身，不再跟随旧目标。
- CI Unix installer smoke 预置坏 symlink，确保后续安装脚本能覆盖旧入口。

### 回归

- `test_install_launchers_enable_default_auto_update`
- GitHub Actions `installer-smoke (ubuntu-latest/macOS)` 中的 stale symlink 覆盖场景。

## 2026-04-30 TUI 缩放后不重绘

### 现象

- 用户缩放 Windows Terminal / WSL 终端字体或窗口后，表格仍按旧窗口尺寸显示。
- 必须手动触发刷新或输入操作后，界面才重新按新尺寸裁剪和清屏。

### 根因

- curses 主循环只在按键、probe 结果或显式 dirty 时重绘。
- 终端尺寸变化没有被当成独立输入源处理；无按键时没有检测 `get_terminal_size()` / `getmaxyx()` 变化。
- `KEY_RESIZE` 不是所有 Windows Terminal + WSL 场景都会稳定及时送达，所以只监听按键事件不够。

### 修复

- 主循环每轮检测实际终端尺寸变化。
- 同时处理 `KEY_RESIZE`。
- 尺寸变化后调用 curses resize/update，清空当前帧，失效 `render_cache`，触发立即重绘。

### 回归

- `test_tui_resize_detection_invalidates_render_cache`
- `test_tui_resize_detection_noops_when_size_is_unchanged`

## 2026-05-01 Windows / Web 终端 plain fallback 边框错位

### 现象

- Windows PowerShell、网页 SSH 终端或未知远程终端会自动进入静态文本 fallback。
- fallback 仍然复用 psql 表格渲染，长边框和长单元格在这些终端里换行后会出现孤立竖线、大片空白和底部多余横线。

### 根因

- 旧 fallback 只规避了 curses，但没有规避 psql 宽表边框。
- psql 边框要求终端稳定支持等宽字符宽度和不换行输出；Windows 原生终端和部分 Web 终端不满足这个假设。

### 修复

- 交互式 curses TUI 保留原有 psql 表格。
- Windows / Web / 无 curses fallback 改为 Rich 无边框安全 plain renderer。
- 安全 plain renderer 按终端宽度裁剪，每行不超过 `TRADECAT_TERMINAL_PLAIN_WIDTH` 或当前终端宽度上限，避免长边框换行错位。

### 回归

- `test_tui_safe_plain_fallback_uses_borderless_width_capped_output`
- `test_tui_safe_plain_renderer_handles_wide_snapshot_without_psql_borders`

## 2026-05-02 Win11 Windows Terminal 被误降级到静态兼容模式

### 现象

- 用户在 Win11 Windows Terminal 的 PowerShell tab 中运行 `tradecat`。
- 程序没有进入交互式 TUI，而是输出静态列表并提示“当前终端已进入静态兼容模式；按 Enter 退出。”

### 假设

- H1：Windows Terminal 没有安装 `windows-curses`，导致无法进入 curses。
- H2：Rich fallback 误判终端宽度，导致用户以为进入了错误模式。
- H3：代码对 `sys.platform == "win32"` 无条件降级，阻止了稳定 Windows Terminal 使用 curses。

### 实验

- 检查 `pyproject.toml`：已声明 `windows-curses>=2.4.0; platform_system == 'Windows'`。
- 检查 `src/tradecat_terminal/tui.py`：`_plain_mode_reason()` 对 `sys.platform == "win32"` 直接返回 `windows_plain_reason`。
- 检查截图：运行环境是 Windows Terminal 顶部 tab，而不是传统 cmd 控制台。

### 根因

- 根因是平台判断过粗：所有 Windows 原生运行都被强制降级，导致 Windows Terminal 这种稳定终端即使具备 `windows-curses` 也无法进入交互 TUI。

### 修复

- 增加 `_windows_native_curses_allowed()`。
- Windows Terminal / VS Code Terminal / WezTerm / Alacritty / Kitty 等稳定终端允许交互 TUI。
- 未知 Windows 控制台继续自动降级；可用 `TRADECAT_TERMINAL_ALLOW_WINDOWS_CURSES=1` 明确放行。

### 回归

- `test_tui_windows_terminal_uses_curses_when_available`
- `test_tui_windows_native_can_allow_curses`
- `test_tui_windows_native_defaults_to_plain`

## 2026-05-17 auto-paper systemd 无事件与未开纸单

### 现象

- user-systemd `tradecat-auto-paper.timer` 正常触发 oneshot service，但 runtime cycles 长时间记录 `SKIPPED_NO_EVENT`。
- 同一仓库工具在交互 shell 中可读取 `event_stream` 与 `anomaly_panel`。
- 修复入站后，service 能处理新事件并选出候选，但纸面执行仍因 `agent_sizing_required` 被拒绝。

### 根因

- user-systemd manager / unit 没有继承交互 shell 的网络代理环境，Google Sheets 请求在 service 内变成 `tradecat_auto.source_error.v1`。
- TradeCat 当前无默认 paper order amount、无默认 margin cap、无默认 leverage；缺少 Agent 显式 `agent_margin_usdt` + `paper_leverage` 时，风险门必须拒绝而不是回退旧默认。

### 修复

- 在本机 user-systemd service drop-in 中加入本地代理环境，并执行 `systemctl --user import-environment`、`daemon-reload`、重启 timer，再立即触发一次 service cycle。
- 保持 sizing 环境为空；不把任意数值写成 TradeCat 默认。

### 回归

- `start-auto-paper.sh health --json` 恢复 `healthy`，archive 出现 `PROCESSED` 与后续 `SKIPPED_DUPLICATE_EVENT`。
- 最新 processed cycle 读取 `event_stream` 成功，选中 `CYSUSDT`，但 `risk_decision.reasons=["agent_sizing_required"]`、`paper_execution.status=REJECTED`，符合无默认 sizing 契约。
- safety flags 保持 `real_orders=false`、`signed_requests=false`、`reads_api_keys=false`。

## 2026-05-17 Agent market context contract audit blockers

### 现象

- 独立只读审查发现多个 `tradecat_auto.*.v1` 子 payload 只有 `schema`，缺少 `schema_version`。
- 缺 Agent sizing 的 paper run 顶层仍可能 `ok=true`，CLI 会按成功退出。
- ledger 层对缺 `leverage` 的 OPENED execution 会回退 `1.0` 并开仓。
- Agent context 中显式安全边界 `signed_requests=false`、`reads_api_keys=false` 会被误判为 credential-like key。

### 根因

- schema/version 门禁只覆盖了部分顶层报告，未覆盖 enrichment/signal/strategy/risk/paper execution/ledger 等嵌套机器契约。
- pipeline 的 `ok` 只表达计算链路成功，未把 paper 风控拒绝/执行拒绝映射到稳定失败 payload。
- paper ledger 仍保留旧默认 leverage 兜底，和“Agent/Hermes 必须显式 sizing/exits”契约冲突。
- credential key 扫描没有区分“携带凭证材料”和“显式 false 安全声明”。

### 修复

- 给 `project/src/tradecat_auto/*.py` 内公开 `tradecat_auto.*.v1` payload 补 `schema_version=1.0.0`。
- paper 模式下风险非 ALLOW 或 paper execution 未 OPENED 时，`run_once_report.ok=false` 并输出对象型 `error.code`。
- `apply_paper_execution()` 在 ledger 层对缺 leverage 或缺等价 explicit sizing 的 OPENED execution fail-closed，记录 `agent_sizing_required`，不落 open position。
- 允许 `requires_signature=false`、`signed=false`、`signed_requests=false`、`reads_api_keys=false`、`read_api_keys=false` 这类安全声明；true 或实际 credential-like key 仍拒绝。

### 回归

- 最小实验确认缺 sizing：`run_once_report.ok=false`、`error.code=agent_sizing_required`、`paper_execution.status=REJECTED`。
- 最小实验确认 sized context 的 `enrichment/signal/strategy_intent/risk_decision/paper_execution` 均有 `schema_version=1.0.0`。
- 最小实验确认 ledger 缺 sizing 不开仓，`last_rejected_execution.reason=agent_sizing_required`。
- 最小实验确认 false safety flags audit `ok=true`。
