# sheets-service

将本地生成的“TG 卡片事件（CardEvent）”同步到 Google Sheets 公共看板。

## 配置（环境变量）

说明：
- `scripts/start.sh` 会按顺序加载：`<repo>/config/.env`（只读）→ `<service>/.env`（本地私密，不提交）。
- 你也可以直接在 shell 里 `export` 这些变量（纯 CLI）。

- `SHEETS_WRITE_MODE`：写入模式 `webhook|sa`（默认 `webhook`）

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
- `SHEETS_DASHBOARD_COL_L` / `SHEETS_DASHBOARD_COL_R`：看板固定列区间（默认 `A..M`）
- `SHEETS_DASHBOARD_MODE`：`replace|append`（默认 `replace`；同类卡片覆盖写，避免持续堆叠）
- `SHEETS_DASHBOARD_SLOT_HEIGHT`：replace 模式槽位“最小预留高度”（行数，默认 10；实际预留高度会随卡片高度增长并记录在 `元数据.slot.<card_type>.h`）
- `SHEETS_FACTS_MODE`：`append|none`（默认 `append`；若工作簿触发 1000 万 cells 上限，需要设为 `none` 仅保留看板覆盖写）
- `SHEETS_BLOB_THRESHOLD_CHARS`：raw 超长阈值（默认 20000；超长会落 Drive 并在表内存引用）
- `SHEETS_SA_WRITE_RPM`：SA 写入限流（写请求/分钟，默认 55；配额为 60 时建议 50）

### 导出与运行
- `SHEETS_EXPORT_LANG`：默认 `zh_CN`
- `SHEETS_EXPORT_CARDS`：逗号分隔 card_id 白名单；空=全部
- `SHEETS_EXPORT_INCLUDE_BLACKLIST`：`1` 表示包含 cards registry 黑名单卡片
- `SHEETS_EXPORT_MULTI_PERIODS`：`0/1`（默认 `1`；对排行榜卡片导出 7 周期横向表：`1m..1w`）
- `SHEETS_SYNC_INTERVAL_SECONDS`：daemon 模式间隔（默认 60）
- `SHEETS_IDEMPOTENCY_DB_PATH`：本地幂等键库（默认 `data/idempotency.db`）

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
