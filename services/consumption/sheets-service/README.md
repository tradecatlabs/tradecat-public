# sheets-service

将本地生成的“TG 卡片事件（CardEvent）”同步到 Google Sheets 公共看板。

## 配置（环境变量）

说明：
- `scripts/start.sh` 会按顺序加载：`<repo>/config/.env`（只读）→ `<service>/.env`（本地私密，不提交）。
- 你也可以直接在 shell 里 `export` 这些变量（纯 CLI）。

- `SHEETS_WRITE_MODE`：写入模式 `webhook|sa`（默认 `webhook`）
- `SHEETS_SYNC_MODE`：同步模式 `dashboard|snapshot|append`
  - `dashboard`（SA 推荐，默认）：每轮 **reset 看板并全量重绘**，紧凑排布，不依赖 slot 预留高度，不会出现“卡片间空洞/错位/堆叠”。
  - `snapshot`：走 outbox + 幂等，只写“新卡片事件”；适合需要事实表 append 的场景。
  - `append`：保留口径（目前与 `snapshot` 行为一致，历史兼容）。
- `SHEETS_FORCE_RENDER`：`1` 表示强制重渲染（忽略幂等，用于版式/样式大改后刷新）

### Webhook 模式（Apps Script，可选）
- `SHEETS_WEBHOOK_URL`：Apps Script Web App URL（`.../exec`）
- `SHEETS_WEBHOOK_SECRET`：HMAC 密钥
- `SHEETS_WEBHOOK_TIMEOUT_SECONDS`：请求超时（默认 10）
- `SHEETS_WEBHOOK_MAX_RETRIES`：失败重试次数（默认 3；仅对 429/5xx/网络错误生效）
- `SHEETS_WEBHOOK_BACKOFF_BASE_SECONDS`：退避基数（默认 1.0）
- `SHEETS_WEBHOOK_BACKOFF_MAX_SECONDS`：退避上限（默认 30.0）

### SA 模式（Service Account + Sheets API，全 CLI，推荐）
- `GOOGLE_APPLICATION_CREDENTIALS`：SA key.json 路径（或 `SHEETS_SA_CREDENTIALS_PATH`）
- `SHEETS_SPREADSHEET_ID`：目标工作簿 id（可用 `--bootstrap` 创建）
- `SHEETS_PUBLIC_READ`：`1` 表示将工作簿设为“任何人有链接可读”
- `SHEETS_SHARE_EMAIL`：可选，授权某个邮箱为 writer（不发通知）
- `SHEETS_DRIVE_FOLDER_ID`：可选，把工作簿/Blob 放入指定 Drive 目录
- `SHEETS_DASHBOARD_COL_L` / `SHEETS_DASHBOARD_COL_R`：看板列区间（默认：多周期 `A..BS`，否则 `A..M`）
- `SHEETS_DASHBOARD_AUTO_WIDTH`：`0/1`（默认 `1`；`dashboard` 模式下自动把 `col_r` 扩到“足以容纳本轮最大列数”，避免“超宽表头被纵向分块”让人误以为列丢失）
- `SHEETS_DASHBOARD_MODE`：`replace|append`（默认 `replace`；同类卡片覆盖写，避免持续堆叠）
- `SHEETS_DASHBOARD_SLOT_HEIGHT`：replace 模式槽位“最小预留高度”（行数，默认 10；实际预留高度会随卡片高度增长并记录在 `元数据.slot.<card_type>.h`）
- `SHEETS_FACTS_MODE`：`append|none`（默认 `append`；若工作簿触发 1000 万 cells 上限，需要设为 `none` 仅保留看板覆盖写）
- `SHEETS_BLOB_THRESHOLD_CHARS`：raw 超长阈值（默认 20000；超长会落 Drive 并在表内存引用）
- `SHEETS_SA_WRITE_RPM`：SA 写入限流（写请求/分钟，默认 55；配额为 60 时建议 50）

### 远程数据源（SSH 拉取服务器 market_data.db，可选，推荐）

> 用途：当本机 `libs/database/.../market_data.db` 不全/落后时，sheets-service 可在每轮同步前先从服务器拉取一份快照作为数据源。

- `SHEETS_REMOTE_DB_MODE`：`off|ssh`（默认：检测到 `SHEETS_REMOTE_DB_SSH_HOST` 则自动启用 `ssh`）
- `SHEETS_REMOTE_DB_SSH_HOST`：SSH 主机（例如 `100.91.176.84`）
- `SHEETS_REMOTE_DB_SSH_USER`：SSH 用户（默认 `nvidia`）
- `SHEETS_REMOTE_DB_SSH_KEY_PATH`：SSH 私钥路径（建议 `chmod 600`）
- `SHEETS_REMOTE_DB_PATH`：远端 DB 路径（例如 `/home/nvidia/.../market_data.db`）
- `SHEETS_REMOTE_DB_LOCAL_PATH`：本地落地路径（默认 `data/remote/market_data.db`）
- `SHEETS_REMOTE_DB_MIN_REFRESH_SECONDS`：最小刷新间隔（默认 300；避免每次都传 170MB）
- `SHEETS_REMOTE_DB_SNAPSHOT`：`0/1`（默认 `0`；`1` 表示先在远端生成一致性快照再拉取，避免并发写入导致 DB 不一致）

### 导出与运行
- `SHEETS_EXPORT_LANG`：默认 `zh_CN`
- `SHEETS_EXPORT_CARDS`：逗号分隔 card_id 白名单；空=全部
- `SHEETS_EXPORT_INCLUDE_BLACKLIST`：`1` 表示包含 cards registry 黑名单卡片
- `SHEETS_EXPORT_MULTI_PERIODS`：`0/1`（默认 `1`；对排行榜卡片导出 7 周期横向表：`1m..1w`）
  - 列顺序：按“字段组”展开周期（`趋势强度@1m..1w` → 下一字段组 …），并在看板渲染时生成“两行表头”：字段组行 + 周期行。
- `SHEETS_HIDE_PERIODS`：隐藏指定周期列（仅影响展示，不删除数据；默认 `1m`）
  - 示例：`SHEETS_HIDE_PERIODS=1m` / `SHEETS_HIDE_PERIODS=1m,1w`
  - 禁用：`SHEETS_HIDE_PERIODS=off`
- `SHEETS_EXPORT_SYMBOLS_GROUPS`：导出侧覆盖 `SYMBOLS_GROUPS`（例如 `main4`），避免继承全局配置导致看板币种不全
- `SHEETS_EXPORT_SYMBOLS_UNFILTERED`：`0/1`（`1` 表示导出侧强制关闭币种过滤，等价 `SYMBOLS_GROUPS=auto`）
  - 常见现象：如果你的全局 `config/.env` 是 `SYMBOLS_GROUPS=main1`（仅 BTC），看板会“只有 BTC”。此时无需改全局配置，只需在 sheets-service 侧设置以上变量即可。
- 看板源信息：每张卡片的 `标题/更新/排序/提示/最后更新` 会按固定顺序拼接到 **同一单元格**（整行合并），紧贴在表格主体上方。
- `SHEETS_SYMBOL_TABS`：逗号分隔交易对（默认取 `SYMBOLS_GROUP_main4`，再回退 `BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT`），为每个交易对创建一个中文前缀的子表 `币种查询_<SYMBOL>` 并覆盖写“币种查询真表格（结构化字段）”。
- `SHEETS_SYMBOL_TAB_PREFIX`：子表名前缀（默认 `币种查询_`）
- `SHEETS_SYMBOL_TABS_MODE`：`dashboard|every|none`（默认 `dashboard`；仅在 dashboard 全量重绘时刷新子表；`every` 表示 snapshot 模式也刷新，写入量更大）
- `SHEETS_SYMBOL_TABS_INTERVAL_SECONDS`：子表刷新最小间隔（默认 900；仅对 `dashboard` 模式下的子表刷新节流生效）
- `SHEETS_SYNC_INTERVAL_SECONDS`：daemon 模式间隔（默认 60）
- `SHEETS_IDEMPOTENCY_DB_PATH`：本地幂等键库（默认 `data/idempotency.db`）

### Polymarket 统计（旁路子表，可选）

在同一工作簿内新增一个子表（默认名：`Polymarket统计`），展示服务器 polymarket 服务的 `csv-report.js` 统计输出。

- `SHEETS_TAB_POLYMARKET_STATS`：子表名称（默认 `Polymarket统计`）
- `SHEETS_POLYMARKET_STATS_ENABLE`：`0/1/auto`（默认 `auto`；`auto` 表示“能导出就导出”，否则跳过）
- `SHEETS_POLYMARKET_STATS_INTERVAL_SECONDS`：最小刷新间隔（默认 900）
- `SHEETS_POLYMARKET_MODE`：`auto|local|ssh`（默认 `auto`；优先 ssh）
- `SHEETS_POLYMARKET_SERVICE_DIR`：polymarket 服务目录（包含 `scripts/csv-report.js`）
- `SHEETS_POLYMARKET_LOG_FILE`：日志路径（相对 `SERVICE_DIR` 或绝对路径；默认优先 `$HOME/.local/state/tradecat/polymarket.log`，否则回退 `logs/polymarket_bot.log`）
- `SHEETS_POLYMARKET_MAX_LOG_MB`：日志最大大小（默认 200；防止误扫 7GB 导致超时）
- `SHEETS_POLYMARKET_TIMEOUT_SECONDS`：导出超时（默认 30）
- `SHEETS_POLYMARKET_TRANSLATE`：`0/1`（默认 `0`；禁用翻译避免外部依赖与副作用）
- `SHEETS_POLYMARKET_ENABLE_API_RANKINGS`：`0/1`（默认 `0`；`1` 才会请求 polymarket gamma API）
- `SHEETS_POLYMARKET_SSH_HOST/SHEETS_POLYMARKET_SSH_USER/SHEETS_POLYMARKET_SSH_KEY_PATH`：ssh 参数（默认复用 `SHEETS_REMOTE_DB_SSH_*`）
- `SHEETS_POLYMARKET_REMOTE_SERVICE_DIR` / `SHEETS_POLYMARKET_REMOTE_LOG_FILE`：ssh 模式下覆盖远端路径（可选；默认优先 `$HOME/.local/state/tradecat/polymarket.log`）
- `SHEETS_POLYMARKET_COMPACT_GRID`：`0/1`（默认 `1`；收缩网格，让右侧无单元格）
- `SHEETS_PRUNE_KEEP_POLYMARKET_STATS`：`0/1`（默认 `1`；`--prune-tabs` 时保留该 tab）

### 币种查询子表（真表格）版式说明

当前“币种查询”不再写入整段 TXT，而是写入可筛选/可排序的结构化表格（复用主看板方案5的设计思路）：

- 冻结：前 4 行（元信息/说明/目录/全局表头）+ 左侧 3 列（面板/指标组/指标）
- 全局表头只出现一次：`面板 | 指标组 | 指标 | 1m..1w | 原始值 | 1m..1w(raw)`
- 面板列（A）按块纵向合并并交替底色；指标组列（B）按块纵向合并
- `SHEETS_HIDE_PERIODS` 会从展示表里“删除周期列”（默认删除 `1m`）
- `SHEETS_SYMBOL_QUERY_RAW_MODE` 控制是否追加 raw 镜像区（默认 `off`，避免出现 J..P 等额外列；如需启用：`hidden|show`）
- 列宽（可选覆盖）：`SHEETS_SYMBOL_QUERY_COL_WIDTH_PANEL/GROUP/METRIC/PERIOD`（默认更紧凑）

## 运行

```bash
cd services/consumption/sheets-service
make install
make run          # 前台跑一次
make start        # 后台 daemon
make status
```

## SA 模式：全 CLI 初始化工作簿

```bash
cd services/consumption/sheets-service
export SHEETS_WRITE_MODE=sa
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa-key.json"
.venv/bin/python -m src --bootstrap --bootstrap-title "TradeCat TG Cards Dashboard"
```

输出里会给你 `spreadsheet_id` 与链接；把 `spreadsheet_id` 写入 `SHEETS_SPREADSHEET_ID` 后即可正常同步：

```bash
export SHEETS_SPREADSHEET_ID="..."
.venv/bin/python -m src --once --cards super_trend_ranking,macd_ranking,bb_ranking
```

版式/样式更新后需要强制刷新（忽略幂等）：

```bash
.venv/bin/python -m src --once --force
```

## 本地验收（无需 Google）

启动 mock webhook：

```bash
cd services/consumption/sheets-service
.venv/bin/python -m src --mock-webhook --mock-port 18080
```

另一个终端发送（dry-run 写 outbox + flush）：

```bash
export SHEETS_WEBHOOK_URL="http://127.0.0.1:18080/exec"
export SHEETS_WEBHOOK_SECRET="dev-secret"
cd services/consumption/sheets-service
.venv/bin/python -m src --once --cards super_trend_ranking,macd_ranking,bb_ranking
```
