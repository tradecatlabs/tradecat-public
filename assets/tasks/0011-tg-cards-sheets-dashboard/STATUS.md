# STATUS - 进度真相源

## 状态机
- 当前状态：Done

## 进度（估算）

> 口径：以“可在真实 Google Sheet 工作簿持续落地、可幂等重放、可审计无遗漏”为 100%。

- 总进度：100%
- 进度条：`[####################] 100%`
- 当前阶段：M5（看板从 A 列渲染 + 全中文 tab + 超宽列分块 + reset/rebuild 运维命令）
- 下一阶段：M6（可选：Apps Script Webhook 上线 / 写入批量化进一步降配额）

## 决策冻结（执行期默认值）
- 写入通道（默认）：Service Account + Sheets API（B，纯 CLI）
- Webhook（可选）：Apps Script Web App（A），用于“用个人账号写入 + Drive blob 不受 SA 配额限制”的场景
- 看板固定列区间：`A..M`
- 子表命名：全部中文（旧英文 tab 自动迁移为中文）
- 事实表落盘：`cards_index + card_fields_eav + card_rows + row_fields_eav + blobs_index + meta`（全部 append-only）
- 幂等口径：`card_key` 稳定（优先使用 `cards.data_provider.get_latest_data_time()` 作为 ts_utc）
- SA 写入配额：默认启用限流（`SHEETS_SA_WRITE_RPM`，默认 55；远端实配 50）避免 429

## 证据存证（Live Evidence）

### 1) 需求真相源（PRD）hash
- `assets/docs/analysis/tg_cards_google_sheets_dashboard_prd.md` SHA256：
  - `36c1a03046fa7b8708023e488757734312c82339c845acfe54e5e74528971957`
  - Evidence command: `sha256sum assets/docs/analysis/tg_cards_google_sheets_dashboard_prd.md`

### 2) 本地 SA 写入真实工作簿成功（可重复验证）
- Spreadsheet（用户创建并分享给 SA 编辑）：
  - `SHEETS_SPREADSHEET_ID=<your_spreadsheet_id>`
  - SA key（本地私密）：`<your_service_account_key_json_path>`
- Evidence command:
  - `cd services/consumption/sheets-service && SHEETS_WRITE_MODE=sa SHEETS_SPREADSHEET_ID=... GOOGLE_APPLICATION_CREDENTIALS=... .venv/bin/python -m src --once --cards super_trend_ranking,macd_ranking,bb_ranking`
- Observed signal（示例）：
  - 输出包含：`✅ flush 完成 ... mode=sa`

### 3) 分层契约（至少一次 + 幂等）
- Evidence command: `sed -n '1,60p' assets/docs/analysis/layer_contract_one_pager.md`

### 4) 新服务目录已创建（消费层 sheets-service）
- Evidence command: `ls -la services/consumption/sheets-service`

### 5) 远端数据源（nvidia）已部署并 daemon 同步（SSH）
- 远端：`nvidia@100.91.176.84`（repo：`$REMOTE_REPO_ROOT`，legacy services 布局）
- 远端服务：`$REMOTE_REPO_ROOT/services/sheets-service`
- Evidence commands:
  - `export REMOTE_REPO_ROOT="/path/to/tradecat"`  
  - `ssh -i /home/lenovo/.ssh/tradecat_nvidia nvidia@100.91.176.84 'cd $REMOTE_REPO_ROOT/services/sheets-service && ./scripts/start.sh status'`
  - `ssh -i /home/lenovo/.ssh/tradecat_nvidia nvidia@100.91.176.84 'cat $REMOTE_REPO_ROOT/services/sheets-service/data/checkpoint.json && wc -l $REMOTE_REPO_ROOT/services/sheets-service/data/outbox.jsonl'`
- Key observed signal（示例）：
  - 日志包含：`✅ flush 完成 ... mode=sa`

### 6) 离线端到端（mock webhook）已跑通：签名鉴权 + 幂等 + flush（用于无网验收）
- Evidence commands:
  - `cd services/consumption/sheets-service && .venv/bin/python -m src --mock-webhook --mock-port 18080`
  - `cd services/consumption/sheets-service && SHEETS_WEBHOOK_URL=http://127.0.0.1:18080/exec SHEETS_WEBHOOK_SECRET=dev-secret .venv/bin/python -m src --once --cards super_trend_ranking,macd_ranking,bb_ranking`
- Observed signal:
  - 输出包含：`✅ flush 完成`
  - `services/consumption/sheets-service/data/mock_webhook/received.jsonl` 行数增长

### 7) 修复 telegram-service SQLite 默认路径（避免 provider 误指向 services/libs）
- 变更文件：`services/consumption/telegram-service/src/cards/data_provider.py`
- Evidence command: `python3 -m py_compile services/consumption/telegram-service/src/cards/data_provider.py`

## Blocked（如有）
- None

## 下一步（执行 Agent 的首个 P0）
- 如必须“raw 超长 100% 可回取且不依赖 SA Drive”：上线 Apps Script Webhook（用个人账号写入 + Drive blob）。
- 如要更快写入：把 SA writer 从“多请求/卡片”优化到“批量 batchUpdate/批次”，进一步降低配额消耗。
