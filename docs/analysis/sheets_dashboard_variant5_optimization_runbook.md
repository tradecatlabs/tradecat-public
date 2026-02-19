# Runbook：看板方案5（字段纵向×周期横向）优化与渲染执行

## 0) 目标

把 `看板_方案5_字段纵向周期横向` 优化为“真正的表格面板”：

- **全局只保留 1 行表头**：`币种 | 字段 | 1m | 5m | 15m | 1h | 4h | 1d | 1w`
- **冻结**：冻结第 1 行表头 + 冻结前 2 列（币种/字段）
- **每张卡片**：仅渲染 `源信息行（📊...） + body`，不重复表头
- **可读性**：
  - 7 个周期列灰白交替
  - 同一币种在“币种列”纵向合并（一个币种占一个合并单元格）

> 关键约束：冻结列时禁止做“整行 mergeCells”（Sheets 禁止跨冻结列边界合并单元格）。

## 1) 版本基线（回滚锚点）

- 当前推荐基线 commit：`5fae41b`（v5 单全局表头 + 冻结）
- 如需回滚到该点：

```bash
git reset --hard 5fae41b
```

## 2) 币种范围（非常重要）

### 2.1 你要的“币种不乱飞”口径

方案5展示的币种范围，必须跟 `telegram-service` 的过滤一致（默认来自 `SYMBOLS_GROUPS`）。

推荐：明确固定为 main4（BTC/ETH/BNB/SOL），避免导出时币种爆炸：

```bash
export SYMBOLS_GROUPS=main4
export SYMBOLS_GROUP_main4="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT"
export SHEETS_EXPORT_SYMBOLS_UNFILTERED=0
```

> 若你显式设置 `SHEETS_EXPORT_SYMBOLS_UNFILTERED=1`，会强制关闭过滤（不建议，币种会很多）。

## 3) 数据源：服务器 market_data.db（SSH 拉取）

服务端 DB（单一真相源）：

- host：`100.91.176.84`
- user：`nvidia`
- key：`/home/lenovo/.ssh/tradecat_nvidia`
- remote db：`/home/nvidia/.projects/tradecat/libs/database/services/telegram-service/market_data.db`
- local cache：`services/consumption/sheets-service/data/remote/market_data.db`

建议：避免每次都拉 170MB，设置最小刷新间隔（例如 3600 秒）：

```bash
export SHEETS_REMOTE_DB_MODE=ssh
export SHEETS_REMOTE_DB_SSH_HOST="100.91.176.84"
export SHEETS_REMOTE_DB_SSH_USER="nvidia"
export SHEETS_REMOTE_DB_SSH_KEY_PATH="/home/lenovo/.ssh/tradecat_nvidia"
export SHEETS_REMOTE_DB_PATH="/home/nvidia/.projects/tradecat/libs/database/services/telegram-service/market_data.db"
export SHEETS_REMOTE_DB_MIN_REFRESH_SECONDS=3600
```

## 4) Google Sheets 写入：SA 模式（推荐 CLI）

```bash
export SHEETS_WRITE_MODE=sa
export SHEETS_SPREADSHEET_ID="1q-2sXGsFYsKf3nV5u5golTVrLH5sfc0doiWwz_kavE4"
export GOOGLE_APPLICATION_CREDENTIALS="/home/lenovo/.config/gcp/credentials/just-effect-487712-p4-ec65508ad391.json"
```

### 4.1 配额/限流（避免 429）

```bash
export SHEETS_SA_WRITE_RPM=20
export SHEETS_SA_429_RETRIES=20
export SHEETS_SA_READ_RETRIES=6
export SHEETS_WEBHOOK_TIMEOUT_SECONDS=60
```

## 5) 执行：只刷新方案5（不动其他方案/不动事实表）

只生成变体（避免把主看板也全量重绘），并只生成方案5：

```bash
cd services/consumption/sheets-service

export SHEETS_DASHBOARD_VARIANTS=5
export SHEETS_FACTS_MODE=none

.venv/bin/python -m src --once --force --dashboard-variants --dashboard-variants-only
```

验收点（打开 Google Sheet）：

- `看板_方案5_字段纵向周期横向`
  - 只出现 1 次表头行（第 1 行）
  - 冻结：第 1 行 + 前两列
  - 每张卡片第 1 行是 `📊 ...` 源信息行
  - 同一币种单元格纵向合并（A 列）

## 6) 常见问题排查

### 6.1 出现“很多币种”

几乎一定是过滤没生效：

- 检查：`SYMBOLS_GROUPS` 是否为 `main4`
- 检查：`SHEETS_EXPORT_SYMBOLS_UNFILTERED` 是否被设置为 `1`

### 6.2 变体生成失败 429

这不是逻辑错误，是 Google API 写入配额太低：

- 降低 `SHEETS_SA_WRITE_RPM`（例如 15~20）
- 增加 `SHEETS_SA_429_RETRIES`
- 尽量用 `--dashboard-variants-only`，不要每次都重绘主看板

