# PLAN

## 方案选择

### 方案 A（推荐）：复用 backfill，实现“gap → 日期窗口 → download+ingest”

Pros
- 与现有 Vision ZIP 回填链路一致（字段/目录/审计/幂等策略都已成熟）。
- repair 的职责清晰：只负责“认领 gap + 映射时间窗 + 调 backfill + 关 gap”。

Cons
- gap 是时间窗（ms），Vision 是按日/月包，需要做窗口→日期的映射（但这正是治理层该做的工作）。

### 方案 B：repair 直接走 REST 增量补拉

Pros
- 更细粒度（按 ms since 补拉）。

Cons
- 与“对齐 Vision 官方字段/目录”目标偏离；并且 spot trades time 为 us，需要更多单位转换与对账逻辑。

结论：优先做方案 A；方案 B 作为后续增强（尤其是实时尾部修复）。

## 核心改动点（原子清单）

1. 新增 repair 卡片：
   - `src/collectors/crypto/repair/futures/cm/trades.py`
   - `src/collectors/crypto/repair/spot/trades.py`
2. CLI 路由扩展：
   - `services/ingestion/binance-vision-service/src/__main__.py`：补 choices + 分支 import
3. 统一 spot watermark 单位（ms）：
   - `services/ingestion/binance-vision-service/src/collectors/crypto/data/spot/trades.py`：`_update_watermark` 将 `time_us` 转为 `time_ms=time_us//1000`
4. meta 写入增强（如缺）：
   - 确保 repair/backfill 结束时 `finish_run(..., meta=...)` 记录 claimed/closed/rows/压缩线降级次数等。

## 回滚

- repair 卡片与 CLI 是新增路径：回滚仅需撤销新增文件与 CLI choices，不影响事实表。
- watermark 单位变更若造成问题：可临时把 spot watermark 写回 us，但需要同步修正所有读 watermark 的逻辑（因此推荐一次性改干净并补验收 SQL）。

