# PLAN - 技术选型 / 数据流 / 原子变更路径 / 回滚

## 1) 技术选型对比（至少两案）

### 方案 A：Apps Script Webhook（可选）
**Pros**
- “Google 在线表格作为函数”天然成立：`doPost()` 直接是 HTTP 入口。
- 服务端只需 HTTP POST JSON，凭证复杂度低。
- 表格可公开只读，写入仍受控（脚本身份）。
 - Drive blob 可以走“个人账号”，避免 SA Drive 配额为 0 的限制。

**Cons**
- Apps Script 有执行时间/配额限制，需要严格批量写与限流。
- 并发需要 LockService，且调试体验一般。

### 方案 B：Service Account + Sheets API（默认）
**Pros**
- 工程化更强：重试/并发/监控都在服务端掌控。
- 可更精细控制 batchUpdate、错误分类与告警。

**Cons**
- 需要在服务端管理 Google 凭证；部署面更重。
- 仍需把表格分享给 SA 邮箱为编辑。
 - 默认配额较低（常见 `WriteRequestsPerMinutePerUser=60`），必须做写入限流/批量化。

**结论**
- MVP 默认走 **方案 B**（纯 CLI，已验证可跑通并 daemon 同步）；保留方案 A 作为“高可靠 blob/个人账号写入”的增强路径。

---

## 2) 数据流（ASCII）

```text
sheets-service (cards exporter + outbox)
  ├─(1) 复用 telegram-service cards 插件（读本地 SQLite）导出 CardEvent
  ├─(2) enqueue：append JSONL(outbox) + checkpoint
  └─(3) flush：幂等(store) + 重试退避 + 写入限流
        ├─ SA 模式：Sheets API 落事实 + 渲染看板
        └─ Webhook 模式（可选）：POST → Apps Script → 写表/渲染/Drive blob

看板渲染（默认 replace）：
  - 同类卡片（card_type）固定在一个槽位 y 覆盖写，禁止每轮同步向下堆叠
  - 通过 `SHEETS_DASHBOARD_SLOT_HEIGHT` 预留清理区，避免残留与 merge 冲突
```

---

## 3) 原子变更清单（文件级别，执行 Agent 参考）

> 本任务目录只做规划；实际代码改动应发生在 `services/**/src/` 与必要的脚本目录（遵守仓库 AGENTS.md 约束）。

### 3.1 Apps Script（Google 侧）
- 新建 Web App 脚本（不在仓库内）：实现 `doPost(e)`、HMAC 校验、Lock、写表、渲染。
- 约定工作簿内自动初始化/校验 sheet：`看板/卡片索引/卡片字段EAV/...`

### 3.2 sheets-service（仓库内，新服务）
- 新增服务目录：`services/consumption/sheets-service/`
  - `src/card_event.py`：CardEvent 数据模型 + canonicalize（用于稳定签名/幂等）
  - `src/tg_cards_exporter.py`：复用 telegram-service 的 `cards` 插件，从本地 SQLite 生成“卡片渲染文本 + table 结构”
  - `src/webhook_client.py`：Webhook client（HMAC 签名/超时/重试退避）
  - `src/sa_sheets_writer.py`：SA writer（schema 初始化 + facts append-only + 看板渲染 + 写入限流）
  - `src/outbox.py`：本地 outbox（JSONL + checkpoint），用于“旁路不阻塞/断网补写”
  - `src/__main__.py`：入口（`--once/--daemon/--dry-run`、选择 cards、批量投递）

### 3.3 telegram-service（仓库内，延后增强）
- MVP 阶段可不改 telegram-service：sheets-service 直接从本地数据（market_data.db）复用卡片渲染输出。
- 增强阶段再引入 “发送点 hook + outbox enqueue”，实现“真正以 TG 消息为真相源”的同步。

### 3.3 运行脚本/运维（可选）
- 新增：`scripts/` 下验证脚本（执行 Agent 可选）：生成样例 CardEvent 并投递到 Webhook。

---

## 4) 回滚协议（必须可 100% 自愈）

### 4.1 软回滚（推荐）
- 通过环境变量或配置开关禁用同步（例如 `SHEETS_SYNC_ENABLED=0`）
- outbox worker 停止/不再 flush，但不影响 TG 卡片功能

### 4.2 硬回滚
- 撤销 Apps Script Web App 发布或更换 secret（立即阻断写入）
- 清理/归档 outbox（保留证据，避免误删）

### 4.3 数据回滚（展示面）
- `看板` 可直接清空后重建（事实表为真相源）
