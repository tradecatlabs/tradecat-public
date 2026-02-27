# 设计与执行文档：Sheets 看板“无感刷新”（Flicker-Free Refresh）最优方案

## 0) 一句话目标

把当前 `SHEETS_SYNC_MODE=dashboard` 的“整表清空→逐行写回”的可见中间态，升级为：

- 白天常态同步：**不清空整表**、只更新变更卡片、尽量一次提交完成（用户几乎感知不到刷新）
- 夜间维护窗口：允许全量重绘做“碎片整理/对齐修复/样式模板更新”

## 1) 当前现状与问题根因

### 1.1 当前刷新口径（会闪屏）

`dashboard` 模式每轮执行：
1) `reset_dashboard()`：清空看板区值 + 解除合并 + 清格式（浏览器立即看到“全消失”）
2) 逐卡片写入：每张卡至少 2 次写请求（values + formats/merge），中间态可见（浏览器看到“逐行刷回”）

### 1.2 根因

Google Sheets 前端是“实时渲染”的：
- 多次写请求会暴露中间态
- 先 clear 再写回必然造成“空白窗口期”

所以“无感刷新”的根本是：**避免 clear 整表**，并把“值+格式”的更新尽量压缩到最少请求里。

## 2) 最优方案总览（结论）

### 2.1 方案选择

最优工程路线（推荐）：

1) 常态同步走 `snapshot + replace`（增量覆盖写，不 reset）
2) 每轮把变更卡片的更新打包成 **单次 `spreadsheets.batchUpdate`**（尽量原子提交）
3) 样式模板化：把大量 `repeatCell/updateBorders` 从“每轮同步”移到“初始化/变更时同步”
4) 夜间（或手动）跑一次 `dashboard reset+reflow` 作为 defrag/修复工具

> 这条路线在体验、配额、复杂度、稳定性之间是 Pareto 最优点。

## 3) 分阶段执行计划（可直接照做）

### Phase 0：配置切换（立刻止血：不再全表消失）

把 daemon 从：
- `SHEETS_SYNC_MODE=dashboard`

切到：
- `SHEETS_SYNC_MODE=snapshot`
- `SHEETS_DASHBOARD_MODE=replace`
- 保持 `SHEETS_FACTS_MODE=none`（避免 1000 万 cells 上限导致服务卡死）

效果：
- 看板不再整表清空
- 每轮只覆盖变更卡片的槽位区域（可见更新范围缩小）

风险：
- slot 高度缩小时“尾部残留”必须清干净（下一阶段会实现）

### Phase 1：槽位级“无残留覆盖写”

目标：replace 模式下每次更新某卡片时，槽位区域不会残留旧内容/旧格式。

实现要点：
- 写入前对该槽位做局部清理：
  - values：清该槽位 `[col_l..col_r] x [y..y+reserved_height-1]`
  - formats：清该槽位 `userEnteredFormat`（避免背景色/边框残留）
  - unmerge：解除该槽位范围内历史 merge
- 然后写入新内容、再 merge/format

验收：
- 同一 card_type 在 N 次更新后，槽位底部不出现上一次更多行/更多列的残影。

> 你们现在已经做了“局部 clear + unmerge”；补齐“局部清格式”即可做到肉眼无残留。

### Phase 2：单次 batchUpdate（显著降低“逐行刷新感”）

目标：把一次卡片更新从“两次请求（values + formats）”变成“一次请求（updateCells + merges + borders）”。

做法：
- 用 `spreadsheets.batchUpdate` 的 `updateCells` 写值（`userEnteredValue`），替代 `values.batchUpdate`
- 在同一个 batchUpdate 里提交：
  - `updateCells`：写 values
  - `mergeCells`：源信息行整行合并 + 字段组行分段合并
  - `repeatCell/updateBorders`：仅对本卡片槽位需要的样式（或仅写最小样式）

收益：
- 服务器对单卡片更新只发 1 个写请求，前端中间态显著减少（更“瞬间变更”）。

风险：
- `updateCells` payload 更复杂，必须严格计算 range（建议先对 1 张卡做 A/B 验证）。

### Phase 3：样式模板化（配额最优 + 最稳定）

目标：把“每轮/每卡都刷一遍样式”的成本降到接近 0。

做法：
- 新增一次性初始化函数（示例命名）：
  - `ensure_dashboard_template(col_l, col_r)`
- 初始化内容：
  - 表头底色/字体/对齐
  - 表体灰白交替规则（可用条件格式，或固定背景+最小分段）
  - 字段组分隔线（边框）
- 日常同步只写值（或只写极少量 merge），样式不动。

验收：
- 写请求数下降显著（可通过日志统计 request 次数）
- 429 频率明显下降

### Phase 4：夜间 defrag（长期健康）

目标：当 slot 高度逐渐膨胀或位置需要重新紧凑排列时，有一个“维护工具”。

做法：
- 保留 `dashboard reset+全量重绘`，但只在夜间运行：
  - 例如每天 04:00
  - 或手动 CLI：`python -m src --once --force` + `SHEETS_SYNC_MODE=dashboard`

收益：
- 白天无感，夜间彻底整理

## 4) 验收清单（必须可证伪）

### 体验（肉眼）
- 白天刷新时，看板不会整页清空
- 单卡片更新时，只有该卡片槽位变化，不出现“逐行滚动恢复”

### 正确性（数据）
- 每张卡片字段/多周期列不丢
- 同一槽位反复更新无残影（值/背景/竖线都一致）

### 稳定性（运维）
- 写请求数下降（日志可观测）
- 429 显著减少
- 不触发 1000 万 cells 上限（facts 关闭或 rollover）

## 5) 回滚策略

若无感刷新改动导致写入异常：
- 立刻回滚到当前可用的 `snapshot + replace`（不做 batchUpdate/模板化）
- 或在极端情况下回退到 `dashboard` 全量重绘（功能可用但有闪屏）

