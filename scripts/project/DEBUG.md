# TradeCat Terminal Debug Notes

## 当前真相

- 当前仓库根是 Codex Skill 包装层；TradeCat Python 项目根目录是 `scripts/project/`。
- 当前服务是用户侧轻量终端：只读 Google Sheets CSV，写本地 JSON 快照缓存。
- 默认入口 `tradecat` 先打开本地缓存 TUI，再在交互循环内按间隔探测远端；禁止启动前阻塞式全量探针。
- 默认永久保留快照；清理只能通过显式 `tradecat prune --apply` 触发，默认 `prune` 只是 dry-run。
- 默认不压缩快照；如需压缩，使用 `TRADECAT_CACHE_COMPRESSION=gzip`，旧纯 JSON 快照仍可读取。
- TUI 不冻结列、不做右侧列滚动；`←/→` 只用于切换 tap，超出屏幕内容按终端宽度裁剪，用户可缩小字体或扩大窗口查看全表。
- TUI 链接支持两类：交易对跳 Binance Futures，URL 文本直接打开 URL。

## 禁止回退

- 禁止恢复 SQLite / WAL / SQL query / repair / vacuum / cell store 方案。
- 禁止恢复 `freeze_columns`、固定列冻结、右侧列滚动或智能补空白屏幕逻辑。
- 禁止在 TUI 启动前强制同步全部在线表格。
- 禁止把 `datasets/*/writer.py`、`sources/*` 这类空壳重新作为运行契约入口。

## 历史事故索引

旧 SQLite 持久化、压缩 BLOB、repair/backfill、全量 cell store 等事故记录已归档到：

- `scripts/project/DEBUG.archive.md`

该文件只作为历史复盘材料，不是当前运行契约。

## 2026-05-08 安装后 tradecat command not found

### 现象

- 用户在 WSL 内执行 `curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/develop/scripts/project/install.sh | sh`。
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
