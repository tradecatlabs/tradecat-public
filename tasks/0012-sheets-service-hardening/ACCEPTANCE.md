# ACCEPTANCE

## A. 可靠性（网络/代理）

1. `SaSheetsWriter._exec` 对读请求的重试覆盖以下错误（至少其一）并能自动恢复：
   - `SSLError: ... bad record mac`
   - `ConnectionResetError: [Errno 104]`
   - `socket.timeout`
2. 在上述错误触发时，daemon 不退出；本轮失败会记录到日志，并在下一轮继续尝试。

## B. 配额与写入最小化

1. `prune_tabs` 不再“每轮 dashboard 同步都执行”：
   - 默认按间隔执行（例如 6h），或仅当 keep 列表发生变化时执行。
   - 需要在 `meta` 中记录：上次 prune 时间、keep 集合 hash（或等价可审计信息）。
2. `prune_tabs` 失败不影响主流程（现状保持），但失败会被“节流”，避免一轮失败后下一轮立刻重复轰炸。

## C. 运维体验（列宽固化）

1. 提供 CLI 能力输出固定列宽 env（不写入 `.env`，只输出）：
   - 看板：`SHEETS_DASHBOARD_FIXED_COL_WIDTHS=...`
   - 币种查询：`SHEETS_SYMBOL_QUERY_FIXED_COL_WIDTHS=...`
   - Polymarket 三表：`SHEETS_POLYMARKET_FIXED_COL_WIDTHS_*`
2. 按上述配置运行后，刷新不会覆盖用户手工调好的列宽。

## D. 日志与可观测性

1. 默认日志不出现高频 `[DEBUG]`（除非显式开启 debug 开关）。
2. 关键运维动作都有单行摘要日志（例如 prune 是否执行/跳过、原因、耗时/影响 tab 数量）。

## E. 不回归（现有功能不破坏）

1. 看板 v5/币种查询/Polymarket 三表渲染结果字段不丢、不乱（仅版式/可靠性改进）。
2. 既有“纯函数对角线占位”（SPARKLINE）保持生效。

