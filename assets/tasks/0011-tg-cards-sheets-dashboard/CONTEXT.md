# CONTEXT - 现状证据 / 约束矩阵 / 风险图谱

## 1) 需求真相源（PRD）

- PRD 文件：`assets/docs/analysis/tg_cards_google_sheets_dashboard_prd.md`
- 当前版本 SHA256（用于审计锁定）：`090b50122e4e874aee21dbd16aa3a3d9dd39b45ed1f6895a11c5761775f73f9e`
  - Verify: `sha256sum assets/docs/analysis/tg_cards_google_sheets_dashboard_prd.md`

## 2) 仓库内“契约级”约束（强关联）

消费层契约（一页纸）强调：
- “至少一次交付”允许重复，但必须幂等；失败不反向污染上游；缓存可丢可重建。
- 统一时间：存储/接口用 UTC，对外展示可格式化。

证据：
- `assets/docs/analysis/layer_contract_one_pager.md:1`
  - Verify: `sed -n '1,80p' assets/docs/analysis/layer_contract_one_pager.md`

## 3) 当前 TG 卡片形态（可复用的事实）

现有卡片普遍以“标题/更新时间/排序说明/表头/表格行/hint/最后更新”结构渲染，示例：
- 超级趋势：`services/consumption/telegram-service/src/cards/advanced/超级精准趋势排行卡片.py`
- MACD：`services/consumption/telegram-service/src/cards/basic/MACD柱状排行卡片.py`
- 布林带：`services/consumption/telegram-service/src/cards/basic/布林带排行卡片.py`

TG 发送路径存在大量 `reply_text` / `edit_message_text` 调用点，后续同步可选择：
- “在卡片类内部统一 hook”（更集中，但需改动较多卡片）
- “在 bot/app.py 的发送/编辑入口统一 hook”（更集中，风险更可控）

证据（定位调用点）：
- `services/consumption/telegram-service/src/bot/app.py`
  - Verify: `rg -n "reply_text\\(|edit_message_text\\(" services/consumption/telegram-service/src/bot/app.py | head`

## 4) 约束矩阵（来自仓库 AGENTS.md / 项目操作手册）

必须遵守：
- 禁止修改 `config/.env`（生产配置只读）
- 禁止大范围重构
- 禁止添加未经验证的第三方依赖
- 服务边界：telegram-service 不承载信号检测核心逻辑

证据入口：
- 根 `AGENTS.md`（仓库约束与黄金路径）
  - Verify: `sed -n '1,120p' AGENTS.md`

## 5) 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| Webhook 被公开刷写 | High | `requests/min` 异常飙升、Sheet 行数暴涨 | HMAC 鉴权 + nonce + 限流；必要时临时下线 Web App |
| 并发写看板撞块 | High | 出现重复/覆盖卡片块；meta 指针回退 | Apps Script `LockService` 保护 `dashboard_next_row` |
| 原文/JSON 超长丢字段 | High | 单元格被截断/写入失败 | `blobs_index` 外部引用 + hash 校验；表内只存引用 |
| 写表失败拖垮 TG 主链路 | High | TG 发消息延迟上升/超时 | outbox 异步 flush；主链路永不 await 远端写表 |
| 配额/执行时间超限 | Medium | Apps Script 超时、Sheets API 429 | 批量写入、减少单次 API 调用数、退避重试、分片写 |
| SA Drive 配额为 0 | Medium | SA 无法创建新工作簿/Drive blob 失败 | 用户账号创建 Sheet 并分享给 SA；必要时走 Apps Script（个人账号写入 + Drive blob） |
| 字段无限扩展导致成本失控 | Medium | `card_fields_eav` 行数爆炸 | 约束：只对“结构化字段”写 EAV；raw 走 blob；定期归档 |
| 时区混入导致审计错乱 | Medium | ts_utc 与显示时间不一致 | 事实表只存 UTC；展示另外存格式化字段，且可回算 |

## 6) 假设与证伪（Safe-Inference）

> 缺信息不阻塞规划：先给最保守默认值，并提供证伪命令。

| 假设 | 当前默认 | 证伪命令（执行 Agent 后续跑） | 若不成立的调整预案 |
| :--- | :--- | :--- | :--- |
| 写入通道选型 | Service Account + Sheets API（B） | `SHEETS_WRITE_MODE=sa ... python -m src --once` | 改走 Apps Script Webhook（个人账号写入） |
| 看板固定列区间 | `A..M` | `SHEETS_WRITE_MODE=sa ... python -m src --reset-dashboard` 后查看表格列区间 | 改为任意固定区间（不影响事实表） |
| Blob 存储位置 | Google Drive 文件（同账号） | Webhook 写 Drive 并返回 URL | 改为对象存储（S3/R2），表内仍存 URL + hash |
| “每币一个子表” | 不强制（默认用派生视图） | 以用户决策为准 | 若强制：只为白名单 symbols 建表，避免爆表 |
