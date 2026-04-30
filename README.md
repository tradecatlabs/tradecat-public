# tradecat

`apps/tradecat` 是 TradeCat 用户侧终端面板。它只读公开在线表格，把最近快照缓存为本地 JSON 文件，并用 CLI / TUI 做无后端数据库浏览。

当前 monorepo 内保留 Python distribution / package 兼容名 `tradecat-terminal` / `tradecat_terminal`；对外主命令统一使用 `tradecat`。

## 边界

- 只读远端 Google Sheets CSV。
- 只写用户本地快照缓存文件。
- 不使用 SQLite、PostgreSQL 或 TradeCat 服务端生产数据库。
- 不提供本地 SQL 查询层。
- TUI 只读取本地缓存文件；实时刷新也是先拉取 CSV 写缓存，再从缓存渲染。

## 快速开始

```bash
cd apps/tradecat
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

tradecat init
tradecat datasets
tradecat status
tradecat
```

安装后提供三个命令入口：

| 命令 | 用途 |
|:---|:---|
| `tradecat` | 默认直接打开 TUI |
| `tradecat-terminal` | 兼容入口 |
| `tcat` | 短命令别名 |

任意目录直接启动：

```bash
ln -sfn /home/lenovo/.projects/cat/tradecat/apps/tradecat/.venv/bin/tradecat ~/.local/bin/tradecat
```

## 常用命令

```bash
# 默认打开终端面板；先读本地缓存，进入后按 tap 独立间隔探测，默认 event_stream=1.5s
tradecat

# 初始化缓存目录，默认 ~/.tradecat/cache
tradecat init

# 查看 dataset 和缓存状态
tradecat datasets
tradecat status
tradecat doctor

# 同步指定 tap 到文件缓存
tradecat sync event_stream
tradecat sync market_snapshot

# 同步全部 active dataset
tradecat sync-all

# 单次探测；发现变化后写缓存
tradecat probe event_stream
tradecat probe --json

# 裁剪历史快照；默认只预览，不删除
tradecat prune --max-snapshots 100
tradecat prune market_snapshot --max-snapshots 100 --apply

# 后台持续探测
tradecat watch event_stream --interval 5
tradecat watch --interval 60

# TUI
tradecat tui
tradecat tui event_stream
tradecat tui --plain
tradecat tui --no-live
```

## 缓存结构

```text
~/.tradecat/cache/
├── registry.json
└── datasets/
    ├── market_snapshot/
    │   ├── manifest.json
    │   └── snapshots/*.json
    ├── anomaly_panel/
    │   ├── manifest.json
    │   └── snapshots/*.json
    ├── market_stats/
    │   ├── manifest.json
    │   └── snapshots/*.json
    └── event_stream/
        ├── manifest.json
        ├── snapshots/*.json
        └── stream_events.json
```

### Snapshot tap

`market_snapshot`、`anomaly_panel`、`market_stats` 是快照型 tap：

- 每次拉取计算完整 CSV matrix hash。
- hash 不变时不新增快照文件。
- hash 变化时写入一个新的 `snapshots/<time>_<hash>.json`。
- TUI 上下键切换历史快照。

### Event stream tap

`event_stream` 是增量流：

- 每次仍保留最新 CSV 快照。
- 同时按 `时间(北京) + 内容` 生成事件键，写入 `stream_events.json`。
- 重复事件只更新 `seen_count / last_seen_at`。
- TUI 上下键滚动事件列表，不切换批次。

## TUI 操作

| 操作 | 行为 |
|:---|:---|
| `←/→` | 切换 tap |
| `a/d` 或 `Tab` | 切换 tap |
| `↑/↓` | snapshot tap 切换快照；event_stream 滚动事件 |
| `PgUp/PgDn` | 翻行 |
| `n/p` | 选择可见行 |
| `Enter/o` | 打开当前行 URL；无 URL 时打开交易对 Binance Futures 链接 |
| `r` | 重新拉取当前 tap 并写入缓存 |
| `q` | 退出 |

渲染规则：

- 在线表格物理第 1 行显示在顶部文本区，不进入表格区。
- 表格区保留物理列 A/B/C... 和原始行号。
- 表格作为一个整体渲染，不冻结主键列，也不提供右侧列横向滚动。
- 渲染器按真实内容宽度生成 psql 表格，不做按 tap 的自动缩放、撑满空隙或固定宽度省略。
- 终端窗口只负责裁剪当前可见区域；超长内容要看全，直接扩大终端列数或缩小终端字体。
- 终端窗口或字体缩放后，TUI 会检测尺寸变化并立即重绘，不需要手动按 `r`。
- 缓存文件始终保留完整值。

## Dataset

| dataset_key | source | tab | mode |
|:---|:---|:---|:---|
| `market_snapshot` | `market_data` | `全市场快照` | `snapshot` |
| `anomaly_panel` | `market_data` | `异动面板` | `snapshot` |
| `market_stats` | `market_data` | `全市场统计` | `snapshot` |
| `event_stream` | `alternative_data` | `事件流` | `stream` |

## 配置

| 变量 | 默认值 | 说明 |
|:---|:---|:---|
| `TRADECAT_CACHE_DIR` | `~/.tradecat/cache` | 本地快照缓存目录 |
| `TRADECAT_TERMINAL_<DATASET_KEY>_CSV_URL` | 无 | 覆盖指定 dataset 的 CSV URL |
| `TRADECAT_TERMINAL_<DATASET_KEY>_TUI_PROBE_INTERVAL` | 无 | 覆盖单个 dataset 的 TUI live 探针间隔秒数，例如 `TRADECAT_TERMINAL_EVENT_STREAM_TUI_PROBE_INTERVAL=1.5` |
| `TRADECAT_TERMINAL_TUI_PROBE_INTERVAL` | 空 | 全局覆盖 TUI live 探针间隔秒数；未设置时读取 dataset 契约，`event_stream` 默认 `1.5`，其它 tap 默认 `10` |
| `TRADECAT_TERMINAL_<DATASET_KEY>_TUI_FETCH_TIMEOUT` | 无 | 覆盖单个 dataset 的 TUI live 拉取超时秒数，例如 `event_stream` 默认 `1.0` |
| `TRADECAT_TERMINAL_TUI_FETCH_TIMEOUT` | 空 | 全局覆盖 TUI live 探针单次 CSV 拉取超时秒数；未设置时 `event_stream` 默认 `1.0`，其它 tap 默认 `2.0` |
| `TRADECAT_TERMINAL_TUI_DEFAULT_DATASET` | `event_stream` | 无参数 `tradecat` 默认打开 dataset |
| `TRADECAT_CACHE_MAX_SNAPSHOTS` | 空 | `tradecat prune` 未传 `--max-snapshots` 时读取；空表示不启用裁剪 |
| `TRADECAT_CACHE_COMPRESSION` | `none` | 新快照压缩方式；可选 `none` / `gzip`，默认不压缩 |
| `TRADECAT_TERMINAL_RUNTIME_DIR` | `~/.tradecat-terminal/run` | 后台 watch pid/log 目录 |
| `TRADECAT_TERMINAL_WATCH_INTERVAL` | `60` | 后台 watch 间隔秒数 |
| `TRADECAT_TERMINAL_WATCH_DATASET` | 空 | 为空 watch 全部 active dataset |

TUI 高频探针规则：

- 只 probe 当前打开的 tap，不做 `sync-all`。
- TUI 启动后立即发起后台 probe；网络慢不会阻塞界面主循环。
- 滚动、选行、hover 只读内存中的当前 view/render cache，不重复读取 JSON 快照。
- `event_stream` 使用两列轻量渲染，只渲染时间与内容，避免长文本拖慢交互。
- `event_stream` 默认 `interval=1.5s`、`timeout=1.0s`。
- timeout 会被限制为不超过当前 tap 的基础 interval。
- 连续失败自动退避：1 次失败退到 `3s`，2 次退到 `5s`，3 次及以上退到 `15s`；成功后恢复基础 interval。

## 验证

```bash
cd apps/tradecat
bash scripts/verify.sh
```
