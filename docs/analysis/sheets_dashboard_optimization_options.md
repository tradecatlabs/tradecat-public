# 方案集：TG Cards → Google Sheets 看板优化选项（给你决策用）

> 目标：把“展示面稳定性 + 写入配额压力 + 长期可持续审计”三个矛盾点拆开，给出可选的工程化优化路径与权衡。

## 0) 现状约束（不可绕开）

- Google Sheets 工作簿存在 **1000 万 cells 上限**：事实面 append（EAV/rows/blobs）长期必爆；必须 rollover 或外置事实仓。
- Sheets API 写入配额通常较低（常见 60 write req/min/user）：每轮“按卡片逐条写 + 大量格式请求”很容易 429。
- 看板是展示面：允许破坏性重绘（`SHEETS_SYNC_MODE=dashboard`），不需要像数据库一样做强一致事务。

## 1) 优化菜单（K1..K7）

### K1：样式模板化（把“每轮刷格式”变成“一次初始化”）

**做什么**
- 把 `repeatCell/updateBorders/mergeCells` 等格式写入尽量收敛为“初始化/偶发变更”。
- 日常同步只写 values（`values.batchUpdate`）。

**收益**
- 写请求数大幅下降（最直接降低 429）。
- “残留配色/残留竖线”概率下降（格式变化少，reset 范围更确定）。

**代价/风险**
- 需要设计条件格式（ConditionalFormatRule）或固定模板区域；调试成本中等。

**落点（代码）**
- `services/consumption/sheets-service/src/sa_sheets_writer.py`：把格式 requests 从 `_render_dashboard()` 中拆出去（`ensure_dashboard_template()`）。

---

### K2：批量渲染（每轮从 N 张卡 * 2 次 API → 1~3 次 API）

**做什么**
- 在 `dashboard` 模式下：先在内存里计算整张看板的 values 矩阵（以及必要的少量格式请求），一次性提交。
- 同时把 card->range 的计算从“边写边推 y”改为“先算 layout，再写”。

**收益**
- 写请求极小化，吞吐稳定；daemon 可更频繁运行。

**代价/风险**
- 复杂度上升：需要严格计算 range/offset；更依赖验收用例。

**落点（代码）**
- `services/consumption/sheets-service/src/__main__.py`：dashboard 模式改为 `writer.render_dashboard_batch(payloads)`。
- `services/consumption/sheets-service/src/sa_sheets_writer.py`：新增 `render_dashboard_batch()`。

---

### K3：多周期导出加速（减少 7× 卡片 build 成本）

**选项 A（中等改动）**
- 并发导出 7 周期：`asyncio.gather` + semaphore 控并发。
- 对重复 SQL/读库做缓存（同卡同周期/同时间戳）。

**选项 B（大改动，收益最高）**
- 绕过“先渲染 TG 文本再 parse”路径，直接从 SQLite/服务 API 拿结构化结果生成表（彻底去掉 text parser）。

**收益**
- CPU/IO/耗时显著降低；服务器端更稳。

**风险**
- B 需要对每类卡片的数据契约做对齐（工程量大但最正确）。

**落点（代码）**
- `services/consumption/sheets-service/src/tg_cards_exporter.py`

---

### K4：列宽策略固定化（稳定布局，降低心理噪声）

**做什么**
- 固定 `SHEETS_DASHBOARD_COL_R` 为一个足够大的上限（例如你现在自动扩到的 `CU`），并关闭 auto width。

**收益**
- 看板布局完全稳定，不会“这轮变宽/那轮变窄”。

**代价**
- 列更宽（展示面成本，可接受）。

**落点**
- 纯配置（`.env`），可选代码侧禁止自动扩宽。

---

### K5：导出日志降噪（把无关 warn 变成 debug）

**做什么**
- 过滤掉非卡片模块的扫描告警（`模块 xxx 未导出 CARD`）。
- 或把它们降级为 debug，仅在 `SHEETS_DEBUG=1` 打印。

**收益**
- 运维日志更干净，排障更快。

**代价/风险**
- 过滤规则写错可能漏卡片；需要加“导出卡片总数”自检。

**落点（代码）**
- `services/consumption/sheets-service/src/tg_cards_exporter.py`

---

### K6：事实面长期化（解决 1000 万 cells 的唯一正解）

**选项 A：rollover（按月/按周新工作簿）**
- 事实表继续 append，但按周期自动切新表；旧表只读归档。

**选项 B：外置事实仓（推荐）**
- facts 落 SQLite/PG/对象存储；Sheets 只保留“看板 + 查询视图”。

**收益**
- 彻底规避 cells 上限；审计台账真正可持续。

**代价**
- 需要你选择事实仓（以及备份/权限/查询方式）。

**落点（代码）**
- `services/consumption/sheets-service/src/sa_sheets_writer.py`：facts writer 抽象为接口，新增 `DbFactsWriter`/`RolloverSheetsFactsWriter`。

---

### K7：服务器 Python 升级（3.10 → 3.11/3.12）

**做什么**
- 服务器端重建 `.venv` 到 3.11+，重新 lock 依赖并回归一次 `--once --force`。

**收益**
- Google SDK 后续版本支持更稳，减少未来突然 break 的风险。

**代价**
- 一次性迁移成本（可控）。

## 2) 决策表（Impact / Effort / Risk）

| 选项 | 主要解决 | 预期收益 | 工程量 | 风险 |
|---|---|---|---:|---:|
| K1 | 配额/残留 | 中-高 | 中 | 中 |
| K2 | 配额/吞吐 | 高 | 中-高 | 中 |
| K3A | 性能 | 中 | 中 | 低-中 |
| K3B | 性能/正确性 | 高 | 高 | 中-高 |
| K4 | 稳定性 | 中 | 低 | 低 |
| K5 | 可观测性 | 低-中 | 低 | 低 |
| K6A | cells 上限 | 高 | 中 | 中 |
| K6B | cells 上限（根治） | 最高 | 高 | 中 |
| K7 | 依赖可维护性 | 中 | 中 | 中 |

## 3) 我建议你优先考虑的组合（你来拍板）

- 若你当前痛点是“429/不稳定/残留”：先 K4 → K1/K2（二选一，或先 K2 再 K1）。
- 若你要“审计台账长期跑”：必须上 K6（A 快速止血，B 长期正确）。
- 若你要“更快更省 CPU”：K3A（短期）→ K3B（长期）。

