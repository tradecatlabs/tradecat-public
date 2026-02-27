# CONTEXT

## 1) 现状概览（代码真相源）

服务位置：
- `services/consumption/sheets-service/`

关键入口：
- `services/consumption/sheets-service/src/__main__.py`：daemon 循环、dashboard/snapshot 模式分支、自动 prune、Polymarket 旁路导出。
- `services/consumption/sheets-service/src/sa_sheets_writer.py`：Sheets API 写入、样式、冻结、列宽、占位公式、meta 记录、裁剪 grid。

现行能力（已经跑通）：
- 主看板：方案 5（字段纵向 × 周期横向），支持冻结、去重、双色分组、列宽固化。
- 币种查询：结构化真表格，冻结、面板列纵向合并、目录跳转、列宽固化。
- Polymarket：拆分三表（Top15/时段分布/类别偏好），支持面板列、冻结、目录跳转、右对齐、列宽固化；空数据尾列用 SPARKLINE 画对角线占位。

## 2) 已观测问题（症状 → 根因候选）

### 2.1 `prune_tabs` 间歇失败
症状：
- systemd 日志周期性出现：`⚠️ prune_tabs 失败（将继续执行）：SSLError: ... bad record mac`。

根因候选：
- `prune_tabs` 在 `dashboard` 模式下、`schema_mode=minimal` 时每轮执行一次（频率高，放大弱网/代理抖动）。
- `SaSheetsWriter._exec` 对“读请求”重试仅捕获 `TimeoutError`，未覆盖 `SSLError/ConnectionResetError`。

### 2.2 日志噪音高
症状：
- 大量 `[DEBUG]` 与“模块未导出 CARD”告警在常态循环输出，稀释真正故障。

根因候选：
- 使用 `print()` 直写；缺少 log level/开关。

### 2.3 运维操作缺少标准接口
症状：
- 列宽固化依赖临时 python snippet / 手工编辑 `.env`，流程不可审计、不可重复。

根因候选：
- writer 已有 `snapshot_column_widths()` 能力，但 CLI 只覆盖 Polymarket；未覆盖看板/币种查询。

## 3) 平台约束（Google Sheets 语境）

- Sheets 不支持“单元格对角线边框”：只能用 `SPARKLINE` 公式近似绘制。
- 冻结列时禁止跨冻结分割线做横向合并：否则 `updateSheetProperties`/`mergeCells` 会触发 400。
- 配额敏感：常见 `WriteRequestsPerMinutePerUser=60`，必须减少无意义写入与高频维护操作。
- 工作簿上限：约 1000 万 cells；事实表 append-only 必须可关闭（已支持 `SHEETS_FACTS_MODE=none`）。

## 4) 风险量化表

| 风险点 | 严重程度 | 触发信号 | 缓解方案 |
| :-- | :-- | :-- | :-- |
| API 配额爆炸 | High | 429 / 写入延迟明显 | 限流 + 批量化 + 减少每轮维护写 |
| 弱网抖动导致周期失败 | Medium | `SSLError`/`ConnectionResetError` | 读写重试 + prune 调度化 |
| 合并/冻结互斥导致版式错乱 | Medium | 400 / 冻结条消失 | 合并策略严格遵守冻结边界 |
| 文档泄露敏感路径/ID | Low~Medium | repo 内出现真实凭证路径/主机信息 | 文档改为占位符 + env 引用 |

## 5) 假设与证伪（执行 Agent 用）

- 假设 A：`prune_tabs` 的失败主要来自网络抖动而非逻辑 bug  
  - Verify：在弱网环境下手动执行 `--prune-tabs` 多次，观察失败率与错误类型
- 假设 B：把 `prune_tabs` 改为“按间隔执行”即可显著降低失败与噪音  
  - Verify：上线后对比 24h 日志中 `prune_tabs` 调用次数与失败数
- 假设 C：列宽固化通过 CLI 输出 env 行即可覆盖 90% 运维需求  
  - Verify：UI 调整→CLI 输出→刷新后列宽保持不漂移

