# TODO - 微步骤执行清单

> 任务编号：0011  
> 每一项都必须跑 Verify；任何 Gate 未满足不得进入下一项。

## P0（决策冻结 / 环境准备）

[x] P0: 冻结看板列区间（默认 A..M）与最大列宽策略 | Verify: 在 `STATUS.md` 记录冻结项 | Gate: 决策落盘且可复述  
[x] P0: 选择写入通道 A(Webhook) 或 B(SA API) | Verify: 在 `STATUS.md` 记录 | Gate: 明确选择 B 为默认（纯 CLI）  
[x] P0: 创建目标 Google Sheet 工作簿（用户账号创建并分享给 SA 编辑） | Verify: SA 写入返回 `✅ flush 完成` | Gate: `SHEETS_SPREADSHEET_ID` 可写  
[x] P0: 初始化工作簿结构（tab/表头） | Verify: 首次 SA 写入后自动创建所有 tab 与表头 | Gate: `看板/卡片索引/卡片字段EAV/卡片明细行/明细字段EAV/大字段索引/元数据` 全部存在  

## P0（SA 模式：全 CLI 写入验收）

[x] P0: SA 认证可用（token refresh 成功） | Verify: `sheets-service --bootstrap` 失败时先单独 refresh 验证 | Gate: 不再出现 TLS reset  
[x] P0: SA 模式写入真实工作簿（已分享给 SA 编辑） | Verify: `SHEETS_WRITE_MODE=sa ... python -m src --once ...` | Gate: 返回 `✅ flush 完成 ... mode=sa` 且表内出现 `卡片索引` 与 `看板` 内容  
[x] P0: SA 写入限流加固（避免 429 / rpm=60） | Verify: 远端 daemon 持续跑 10 分钟无 429 | Gate: 日志不再出现 `Quota exceeded ... Write requests per minute`  
[x] P0: 远端数据源部署（nvidia）并 daemon 同步 | Verify: `ssh ... ./scripts/start.sh status` | Gate: 日志持续出现 `✅ flush 完成 ... mode=sa`  

## P2（可选增强：Webhook（Apps Script）：鉴权 + 幂等 + 落事实）

[ ] P0: Apps Script 创建 Web App，支持 `POST` JSON | Verify: `curl -sS -X POST "$SHEETS_WEBHOOK_URL" -d '{}' -H 'Content-Type: application/json'` | Gate: 返回 JSON 且无 5xx  
[ ] P0: 实现 HMAC 鉴权（timestamp+nonce+body） | Verify: 发送错签名请求 | Gate: 请求被拒绝且不落盘  
[ ] P0: 实现幂等（cards_index 以 card_key 去重） | Verify: 同 card_key 连续 POST 2 次 | Gate: 第二次 `idempotent=true` 且行数不增长  
[ ] P0: 实现 LockService 保护 `meta.dashboard_next_row` | Verify: 并发 10 个不同 card_key | Gate: 所有 dash_row_y 不重复  
[ ] P0: 写入事实表（index + card_fields_eav） | Verify: 用 Sheets API/手工查看新增行 | Gate: 字段齐全且可追溯  

## P0（离线验收：mock webhook）

[x] P0: 启动 mock webhook 并通过签名验证 | Verify: `cd services/consumption/sheets-service && .venv/bin/python -m src --mock-webhook --mock-port 18080` | Gate: 端口监听且返回 200  
[x] P0: end-to-end：导出 3 张卡片并 flush 到 mock webhook | Verify: `SHEETS_WEBHOOK_URL=http://127.0.0.1:18080/exec SHEETS_WEBHOOK_SECRET=dev-secret .venv/bin/python -m src --once --cards super_trend_ranking,macd_ranking,bb_ranking` | Gate: 输出 `✅ flush 完成` 且 mock 侧收到 3 条  

## P0（telegram-service：outbox 旁路 + 批量投递）

[x] P0: 在 sheets-service 实现 outbox（JSONL + checkpoint） | Verify: 写入 10 条后可断点续传 | Gate: 重启不重复发送  
[x] P0: sheets-service 实现批量 flush（退避重试） | Verify: 断网→恢复→观察 backlog 下降 | Gate: 最终写入成功  
[x] P0: MVP 不改 telegram-service：sheets-service 复用 cards 插件从本地 DB 生成 CardEvent | Verify: `--dry-run` 输出 3 张卡片文本 | Gate: 文本与 TG 卡片结构一致  

## P1（表格型卡片明细化：rows + row_fields_eav）

[x] P1: 为排行榜卡片输出 `table.columns + table.rows[]` | Verify: `--dry-run` / `cards_index` 中 rows_count 对齐 | Gate: columns/rows 完整且无字段遗漏  
[x] P1: SA 落 `card_rows + row_fields_eav` | Verify: Sheet 内行数增长且可筛选 | Gate: 可按 symbol/rank 筛选  

## P1（看板完整渲染）

[x] P1: 实现标准版式渲染（title/update/sort/table/hint/last_update） | Verify: 打开 `看板` 人工比对 | Gate: 版式一致、无错位覆盖  
[x] P1: 实现“超宽字段拆块”策略（按列宽分块纵向堆叠） | Verify: 构造超宽列卡片 | Gate: 不丢字段且看板可读  

## P2（无遗漏：Blob 存储）

[x] P2: 定义 raw 大字段阈值与 blob 落盘策略 | Verify: 设置 `SHEETS_BLOB_THRESHOLD_CHARS=10` 并写入一张带长 raw 的卡片 | Gate: `大字段索引` 有引用且 hash 匹配  
[x] P2: 实现 Drive 上传与引用写入（SA 模式） | Verify: `大字段索引` 出现 URL + sha256 + size_chars | Gate: 可取回且 sha256 一致  

## P2（运维：重放/重建）

[x] P2: 增加 rebuild/reset 命令（从事实表重建/清空看板） | Verify: `--reset-dashboard` + `--rebuild-dashboard` | Gate: 卡片序列恢复  

---

## 可并行（Parallelizable）
- Webhook（Apps Script）与 telegram-service outbox 可并行实现，但必须先冻结 `CardEvent` schema。
- 看板渲染与 EAV/rows 落事实可并行，但上线顺序必须“先事实后渲染”。
