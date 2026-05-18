# tradecat DEBUG

## 2026-04-30 用户侧终端简化为 JSON 快照缓存

### Current Truth

`apps/tradecat` 当前运行口径是：Google Sheets CSV -> 本地 JSON 快照缓存 -> CLI/TUI 展示。服务不再携带后端数据库，不再创建 SQLite schema，不再提供本地 SQL 查询层，也不再执行数据库压缩、vacuum、repair/backfill 等维护流程。

旧 SQLite 章节只作为历史事故和退役背景保留，不能作为当前实现依据。后续修改必须以 `cache.py`、`registry.py`、`sync.py`、`lifecycle.py`、`tui.py` 和 `README.md/AGENTS.md` 的缓存文件契约为准。

### Fix

- 新增 `cache.py`：用 `~/.tradecat/cache` 下的 JSON 文件保存 dataset registry、manifest、snapshot matrix 与事件流增量文件。
- 删除 `db.py`、`query.py`、`storage.py`、`runtime/lock.py` 和 `sql/*.sql`，从代码层移除数据库后端。
- `sync/lifecycle/cli` 改为缓存文件入口；默认 TUI 只读缓存并按需探针当前 tap。
- snapshot tap 保留多批快照；event_stream 独立维护 `stream_events.json`，用 `时间(北京)+内容` 去重并更新 seen 状态。
- TUI 按真实内容宽度生成整表 psql 视图，不冻结主键列，也不提供右侧列横向滚动；终端只裁剪可见区域，不做按 tap 自动缩放、撑满空隙或固定宽度省略。

### Regression

覆盖项：

- `pytest -q tests`：缓存初始化、同步、事件流增量、TUI plain/curses 辅助逻辑、鼠标/交易对链接。
- `ruff check src tests`：缓存文件实现无 lint 错误。
- `compileall src tests`：模块删除后仍可完整编译。

## 2026-04-29 永久事实层压缩 BLOB

### Observation

`market_snapshot` 是 529 x 1694 级别的超宽快照。即使已经移除完整 `dataset_cells` 历史，长期永久保存 CSV 原文与 snapshot 行体仍会持续占用大量 SQLite 空间。

### Root Cause

旧永久事实层把大文本 payload 作为明文 TEXT 存储：`raw_bodies.body_text` 和 `snapshot_row_store.row_json` 会重复保存大量字段名、逗号、JSON 结构和短数值文本。SQLite 页与索引优化不能替代 payload 压缩。

### Fix

- 新增 `codec.py`，统一提供 `zlib` 文本压缩与解压。
- `raw_bodies` 新增 `body_blob/body_codec/compressed_byte_count`；新写入不再保存完整 `body_text` 明文。
- `snapshot_row_store` 新增 `row_blob/row_codec/byte_count/compressed_byte_count`；新写入不再保存完整 `row_json` 明文。
- 历史读取路径兼容旧 TEXT 与新 BLOB；`read_snapshot_batch_rows()` 统一解码后返回原有 dict 结构。
- 新增 `tradecat-terminal storage stats/compress/vacuum`，把旧库明文 payload 显式迁移为压缩 BLOB，并按需 VACUUM 回收文件空间。

### Regression

覆盖项：

- 新同步写入 `raw_bodies` / `snapshot_row_store` 时，TEXT 兼容字段为空，BLOB 字段可用。
- 旧库只有 `body_text/row_json` 时，`storage compress` 可迁移为 BLOB。
- `read_snapshot_batch_rows()` 可读取压缩行体并完整回放历史快照。
- `storage vacuum` 返回文件空间回收报告。

## 2026-04-29 默认永久逻辑存储终态

### Observation

用户侧终端需要默认永久保存在线表格历史，并且要同时支持快照型 tap 的历史回放、事件流 tap 的增量追加、TUI 快速打开和 SQL 可控查询。单纯保留当前镜像会丢历史；把全部宽表展开成历史 cell 又会让 SQLite 膨胀。

### Root Cause

旧模型没有把“原始拉取真相、快照历史、事件流历史、当前视图、查询索引”拆成独立层。历史保存语义只能在 `sheet_row_snapshots/dataset_cells` 和 `sheet_mirror_rows` 之间摇摆，无法同时满足永久回放和轻量运行。

### Fix

- `registry.py` 为每个 active dataset 增加 `data_mode/history_policy/index_columns/event_key_columns/table_region_policy`。
- 新增 `storage.py`，统一处理 CSV 原始记录、表格区域解析、snapshot/stream 写入分流。
- 新增 `raw_bodies/raw_fetches` 保存远端 CSV 原始真相。
- 新增 `dataset_batches/snapshot_row_store/snapshot_row_refs` 保存 snapshot 永久版本；相同 matrix 不新增 batch，相同行体不重复保存。
- 新增 `stream_events` 保存事件流永久事件；相同 event_key 不重复插入，只更新 `seen_count/last_seen_at`。
- 新增 `dataset_current_rows/dataset_index_cells` 分别承载当前视图和关键字段索引，TUI/SQL 不需要默认扫全量历史。
- `TRADECAT_TERMINAL_MAX_BATCHES_PER_DATASET` 默认改为 `0`，旧兼容快照也不再隐式裁剪。

### Regression

覆盖项：

- 初始化数据库会创建永久逻辑存储表。
- registry 输出 `snapshot/stream` data_mode 和 event_key/index_columns。
- 相同 CSV body 只保存一个 raw body，但每次 fetch 都有 raw_fetch 记录。
- snapshot 内容不变不新增 batch；只变一行时只新增变化行体，任意 batch 可完整回放。
- event_stream 重复事件只更新 `seen_count`，新增事件追加。
- `market_snapshot` 仍不写完整 `dataset_cells` 历史。

## 2026-04-28 结构化数据层缺失

### Observation

`tradecat-terminal` 已能从在线表格 CSV 读取行数据，但落库主路径只写入 `sheet_rows.row_json` 与 `sheet_row_snapshots.row_json`。这会把 Google Sheets 的表头、列号、字段名和值关系压扁成 JSON 文本，TUI 只能展示前几个键值，SQL 也难以按字段稳定查询。

### Root Cause

旧实现把在线表格当作“行 JSON 镜像”，没有把在线表格天然存在的结构化契约落为本地数据库索引层。

### Fix

- 保留 `sheet_rows` / `sheet_row_snapshots` 作为完整原始审计层。
- 新增 `dataset_current_cells` / `dataset_cells` 作为结构化当前层和历史批次层。
- 写入时同步维护字段清单、当前单元格、历史单元格。
- `repair` 从已有原始 JSON 行非破坏性重建结构化层，避免内容 hash 未变化时结构化索引缺失。
- TUI 优先读取结构化层，只有旧库未重建时才回退到原始 JSON。

### Regression

覆盖项：

- 写入后可从 `dataset_current_cells` 按字段名查询真实值。
- 写入后可从 `dataset_cells` 按批次查询历史结构化值。
- `repair` 可补齐结构化表。
- TUI 静态输出读取结构化层。

## 2026-04-28 TUI 中文宽字符与终端边界崩溃

### Observation

交互式 `tradecat` 在渲染宽表时出现 `_curses.error: addwstr() returned ERR`。截图中 psql 表格线条、中文字段和长元信息在终端内出现错位、断裂和越界。

### Root Cause

TUI 渲染层把 Python 字符数当成终端显示宽度使用：`len(line)` 计算横向滚动范围，普通字符串切片裁剪屏幕行。中文、全角字符和部分 Unicode 字符的显示宽度大于 1，导致实际写入宽度超过 curses 窗口边界，触发 `addwstr()` 错误；同时横向 viewport 的切片位置也会落在错误显示列上。

### Fix

- 引入显示宽度计算：按 Unicode combining / control / East Asian Width 计算终端显示格。
- `_add_line()`、`_add_table_line()`、`_safe_addstr()` 全部改为显示宽度感知裁剪。
- 横向滚动最大范围改用显示宽度，而不是 `len()`。
- 保留数据库与表格数据完整性，只在 curses viewport 层做显示裁剪。

### Regression

覆盖项：

- 模拟 `addwstr() returned ERR` 时，安全写屏幕会缩短显示内容而不是崩溃。
- 中文宽字符切片后的显示宽度不会超过目标终端宽度。
- `ruff check src tests` 通过。
- `bash scripts/verify.sh` 通过。
- `TERM=xterm-256color script -q -c 'timeout 2s tradecat' ...` 无 Traceback / curses error。

## 2026-04-28 TUI 多 tab 表格错位

### Observation

`anomaly_panel`、`event_stream`、`market_stats`、`market_snapshot` 都复用同一个表格渲染入口。截图中 market_stats 出现中文字段、psql 边框和终端横向显示错位；其它 tab 也存在同类风险。

### Root Cause

旧实现依赖第三方 `tabulate` 生成 psql 文本，但宽字符显示宽度、超宽表 viewport 和 curses 安全写入都在项目内控制。第三方默认输出不属于本项目的显示宽度契约，导致渲染链出现两套宽度认知：表格生成按一套规则，终端裁剪按另一套规则。

### Fix

- 移除 `tabulate` 运行依赖。
- `render_rows_table()` 改为项目内 psql 风格渲染器。
- 表格列宽、padding、分隔线全部使用 `_display_width()` 计算。
- plain 与 curses 继续复用同一套 `render_rows_table()`，所有 tab 一次性生效。
- 文档与 AGENTS 同步禁止回退到第三方表格库默认宽度逻辑。

### Regression

覆盖项：

- psql 输出每一行显示宽度一致。
- CJK 字段列可正确对齐。
- `anomaly_panel` / `event_stream` / `market_snapshot` / `market_stats` plain smoke 均走同一渲染器。
- 伪终端启动 `tradecat` 无 Traceback / curses error。

## 2026-04-28 TUI live 最新批次与历史快照模式

### Observation

用户期望 `tradecat` 打开后默认就是最新实时滚动版本，而不是停留在本地旧缓存；同时仍要能用上下键切换历史快照。

### Root Cause

旧 TUI 只读取 SQLite 当前已有数据，不负责启动探针，也没有 live/history 状态。它能浏览本地数据，但不能保证进入时先更新到最新，也不能区分“实时最新视图”和“用户正在查看历史快照”。

### Fix

- `run_tui()` 默认 live 模式：启动前执行一次 repair/probe，先把最新在线表格写入本地 SQLite。
- curses 主循环按 `TRADECAT_TERMINAL_TUI_PROBE_INTERVAL` 持续探测当前 tab。
- live 模式下强制显示最新批次 `batch_index=0`。
- `↑ / ↓` 切历史快照后进入 history 模式，避免实时刷新打断历史查看。
- `r` 重新探测当前 tab，并回到最新 live 模式。
- CLI 增加 `--no-live` 和 `--probe-interval`，用于离线调试或调整探针间隔。

### Regression

覆盖项：

- CLI 无参数默认进入 live TUI。
- CLI 可用 `--no-live` 禁用实时探针。
- live 模式到达探针间隔后写入并回到最新批次。
- history 模式不会触发探针打断用户。
- 伪终端启动 `tradecat` 无 Traceback / curses error。
- `tradecat-terminal tui event_stream --plain --limit 3 --probe-interval 1` 可实时 probe 到最新事件流。

## 2026-04-28 TUI 启动卡在 all active datasets

### Observation

执行 `tradecat` 后长时间停在：

```text
tradecat: 正在探测最新在线表格数据 (all active datasets) ...
```

进程在进入 curses 面板前占用 CPU；用户看到的现象是“没反应、一直卡”。

### Root Cause

`run_tui()` 在无参数 live 启动时把 `dataset_key=None` 传给 `_probe_latest()`；旧实现把 `None` 解释为 `probe_all_datasets()`。这会在打开 TUI 前同步所有 active dataset，其中包含超宽的 `market_snapshot`，启动路径被全量远端拉取、CSV 解析、SQLite 写入和历史结构处理阻塞。

第二层问题是启动前使用 `repair_local_store()`，它会执行结构化回填；本地库已有大量宽表历史行时，这一步也会拖慢启动。

### Fix

- 新增 `ensure_local_store()`：只初始化 SQLite 和 dataset registry，不做全库结构化回填。
- `run_tui()` 默认 live 启动只探测一个启动 dataset，默认 `event_stream`。
- 新增 `TRADECAT_TERMINAL_TUI_DEFAULT_DATASET`，允许覆盖默认启动 dataset。
- `_probe_latest(dataset_key=None)` 不再触发全量探测，返回错误 payload，防止后续误把 TUI 启动改回全量同步。

### Regression

覆盖项：

- 单元测试确认无参数 live 启动只 probe `event_stream`。
- 单元测试确认 plain 模式不会启动前 probe。
- 伪终端烟测确认启动日志为 `tradecat: 正在探测最新在线表格数据 (event_stream) ...`。
- 伪终端烟测确认 `tradecat` 可进入 live TUI，无 Traceback / curses error。

## 2026-04-28 TUI 运行中卡死与 SQLite FD 泄漏

### Observation

交互式 `tradecat` 进入 TUI 后，界面停在某个 tap，输入响应变慢甚至像卡死。现场 `ps` 显示 `tradecat` 仍在运行并占用 CPU；`lsof ~/.tradecat-terminal/tradecat.db` 显示同一个进程打开了大量 SQLite 文件句柄，FD 从 3、6、8 一直增长到上百个。

### Root Cause

`db.connect()` 返回裸 `sqlite3.Connection`。Python 的 `sqlite3.Connection` 虽然支持 `with conn:`，但这个上下文只负责提交或回滚事务，并不会在退出时关闭连接。TUI 每轮绘制都会读取 datasets、batches、top info、rows；这些 `with connect(...)` 实际都没有 close，最终导致 SQLite FD 泄漏。

第二层问题是 curses 主循环每 1 秒都会完整重画 psql 宽表。宽表列数多时，即使没有输入、没有探针变化，也会持续做整表渲染，放大 CPU 占用和交互迟滞。

### Fix

- `db.connect()` 改为真正的 `@contextmanager`，退出时显式 commit/rollback/close。
- 增加回归测试，确认 `with connect(...)` 退出后连接已关闭。
- TUI 主循环改为 dirty redraw：只有首次绘制、输入改变状态、鼠标滚动、手动刷新或 live 探针触发后才重画。
- 无输入且未到探针周期时不再每秒整表重绘。

### Regression

覆盖项：

- 单元测试确认 SQLite 连接上下文退出后不可再执行 SQL。
- `ruff check apps/tradecat/src apps/tradecat/tests` 通过。
- `pytest -q apps/tradecat/tests` 通过，31 passed。
- `bash scripts/verify.sh` 通过。
- 伪终端 live 烟测期间 `db_fd_count=0`，CPU 约 1%，无 Traceback / curses error。

## 2026-04-28 TUI 交易对链接跳转

### Observation

终端 TUI 已能展示在线表格镜像，但交易对只是普通文本。用户在 TUI 中看到 `交易对` / `合约代码` 后，无法像在线表格超链接一样直接跳到交易页面。

### Root Cause

TUI 展示层之前只负责表格渲染，没有“当前选中行”和“交易对列推断”两个状态。在线表格镜像按 A/B/C 物理列保存，交易对不一定总在固定列，必须从最近的表头行推断。

### Fix

- 增加 `n / p` 可见行选择状态。
- 增加 `Enter / o` 打开当前选中行交易对链接。
- 增加交易对单元格 hover 下划线链接态。
- 增加鼠标左键点击交易对单元格后选择并打开链接，点击非交易对单元格不跳转。
- 从当前行向上扫描最近的 `交易对` / `合约代码` / `symbol` 表头列，按 USDT 永续口径标准化符号。
- WSL 使用 `cmd.exe /c start` 打开浏览器，Linux 使用 `xdg-open`，macOS 使用 `open`。

### Regression

覆盖项：

- `BTC` / `BTCUSDT` / `BTC/USDT` / `BTC-USDT` 标准化为 `BTCUSDT`。
- A/B/C 镜像表通过最近表头行推断交易对列。
- 键盘选中行打开 Binance futures URL。
- 鼠标 hover 只有落在交易对单元格内才进入链接态。
- 鼠标点击交易对单元格打开 Binance futures URL，点击同一行其它单元格不跳转。

## 2026-04-28 TUI hover 不实时、点击不稳定

### Observation

交易对单元格下划线不是鼠标移动过去就出现，而是需要先点击或多次点击后才出现；点击交易对单元格也不是每次立即打开浏览器。

### Root Cause

`curses.mousemask()` 只告诉 curses “愿意接收鼠标事件”，但很多终端不会默认把鼠标移动事件上报给程序。Windows Terminal / xterm 需要显式开启 xterm mouse tracking，否则程序只能在点击时收到事件，下划线自然只能在点击后才刷新。

第二层问题是左键点击只识别 `BUTTON1_CLICKED`。不同终端实际可能发送 `BUTTON1_PRESSED` 或 `BUTTON1_RELEASED`，导致点击动作被漏判。

### Fix

- TUI 进入 curses 后显式开启 `1006` SGR mouse mode 和 `1003` all-motion tracking。
- TUI 退出时关闭上述 mouse tracking，避免污染终端状态。
- 鼠标移动到交易对单元格时立即更新 `hover_row_offset` 并触发重绘。
- 左键点击兼容 `BUTTON1_CLICKED`、`BUTTON1_PRESSED`、`BUTTON1_RELEASED`。

### Regression

覆盖项：

- 鼠标移动到交易对单元格，即使没有点击，也会返回 dirty 并更新 hover 行。
- 左键 pressed 事件可直接打开交易对链接。
- 滚轮仍只改变纵向滚动。

## 2026-04-28 TUI 启动后闪退并泄漏 `35;52;58M`

### Observation

执行 `tradecat` 后，TUI 打印启动探针信息后立即退回 shell，shell 中残留 `35;52;58M` 这类字符。

### Root Cause

这是 SGR mouse tracking 的原始鼠标序列后半段。终端发送的完整形态类似 `ESC [ < 35 ; 52 ; 58 M`。旧代码把 `ESC` 仍然当成退出键处理，程序看到 `27` 后直接退出，后续 `35;52;58M` 没被 curses 消费，泄漏到了 shell。

第二层问题是部分 curses/terminfo 组合不会把 SGR mouse 序列自动转换成 `KEY_MOUSE`，因此不能只依赖 `curses.getmouse()`。

### Fix

- TUI 不再把 `ESC` 作为退出键；退出只保留 `q / Q`。
- 当读到 `ESC` 时，尝试解析后续 `ESC [ < button ; x ; y M/m` 原始 SGR 鼠标序列。
- SGR move / click / wheel 事件复用同一套 hover、打开链接和滚动逻辑。

### Regression

覆盖项：

- `"[<35;52;58M"` 可被解析为 `(35, 51, 57, "M")`，不会泄漏半截序列。
- SGR hover 事件不需要点击即可更新链接 hover。
- SGR 左键 press 事件可直接打开交易对链接。
- 伪终端烟测可保持 TUI 运行到 timeout，并在退出时关闭 mouse tracking。

## 2026-04-28 TUI live 探针网络卡死

### Observation

`tradecat` 进入 TUI 后报错或长时间无响应，堆栈停在 `urllib.request.urlopen()` 读取 Google Sheets CSV。用户手动 `Ctrl-C` 后看到 `KeyboardInterrupt`，说明卡死点在 TUI 主循环里的同步网络请求。

### Root Cause

TUI 主循环 `_maybe_probe_live()` 直接执行 `probe_dataset()`，最终调用 `fetch_csv_body()`。该函数默认 `timeout=30.0`，在 Google Sheets 网络慢、代理不稳或 SSL 读阻塞时，整个 curses 交互主线程被 `urlopen()` 占住，界面无法响应。

### Fix

- 增加 TUI 专用 `TRADECAT_TERMINAL_TUI_FETCH_TIMEOUT`，默认 2 秒。
- `probe_dataset()` / `collect_validate_hash_with_mirror()` 支持传入 `fetch_timeout`。
- TUI startup probe、live probe、手动 `r` 刷新都使用短超时。
- `KeyboardInterrupt` 在 TUI 探针层转成错误 payload，避免 traceback 打穿 curses。

### Regression

覆盖项：

- TUI live probe 会把 fetch timeout 传到 `probe_dataset()`。
- TUI 默认 fetch timeout 是 2 秒，最小钳制为 0.5 秒。
- 原有 sync/probe/watch 测试仍保持默认 30 秒服务级行为。
