# PLAN - 任务决策与路径

> 任务编号：0002

## 1) 目标与非目标

- 目标：把运行库 `crypto.raw_futures_um_trades` 从旧结构升级为 ids + DOUBLE，且 **正式表名不变**（rename-swap），迁移可回滚。
- 非目标：本任务不改采集代码、不建派生层、不动 `config/.env`。

---

## 2) 技术选型对比（至少 2 方案）

| 方案 | 做法 | Pros | Cons | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| A. 原表原地改造 | `ALTER TABLE` 重命名列、改类型、改主键 | 少一份数据副本 | hypertable 上大改锁风险极高；NUMERIC→DOUBLE 会整表重写；回滚困难 | 不选 |
| B. 新表回迁 + rename-swap | 建 `*_new`（目标结构）→ 分批 `INSERT..SELECT` 回迁 → 对账 → swap | 可对账、可回滚、锁窗口短；适配大表 | 需要额外磁盘/WAL；实现步骤更多 | **选择** |

---

## 3) 逻辑流图（数据流向）

```text
------------------------------+         +-----------------------------+
| old: crypto.raw_futures_um  |         | core.* (venue/instrument/   |
| _trades (exchange,symbol)   |--map--> | symbol_map)                 |
+------------------------------+         +-----------------------------+
               |                                       |
               |  batch copy (by time window)          |
               v                                       v
+--------------------------------------------------------------+
| new: crypto.raw_futures_um_trades_new (venue_id,instrument_id)|
+--------------------------------------------------------------+
               |
               | verify (counts/min/max/unmapped)
               v
+--------------------------+
| rename swap (atomic-ish) |
+--------------------------+
```

---

## 4) 原子变更清单（文件级/操作级，不写业务代码）

1. Preflight：确认端点、确认旧表结构、确认 Timescale 扩展存在。
2. Freeze Writes：暂停实时采集/回填写入（或进入维护窗口）。
3. Build Core Mapping：为旧表里出现的 `(exchange,symbol)` 补齐 `core.venue/core.instrument/core.symbol_map`。
4. Create New Hypertable：创建 `crypto.raw_futures_um_trades_new`（目标列/目标 PK/整数 hypertable）。
5. Batch Backfill：按时间窗口分批 `INSERT..SELECT` 从旧表回迁到新表（同时 cast NUMERIC→DOUBLE）。
6. Verify：对账（按 symbol、按窗口），并确认无 unmapped rows。
7. Rename Swap：`raw_futures_um_trades` → `_old`；`*_new` → 正式名。
8. Post-check：确认 hypertable、压缩设置、policy、主键、写库烟囱测试。
9. 保留回滚：保留 `_old` 至少 N 天（由运维决定），之后再清理。

---

## 5) 回滚协议（必须可 100% 还原）

触发条件（任一满足即回滚）：

- swap 后验收 A1/A2/A3 任一失败
- 新采集写库出现错误（列不存在/主键冲突异常/吞吐崩）

回滚步骤（只做 rename，不做重拷贝）：

1. 停写（同 Freeze Writes）。
2. `ALTER TABLE crypto.raw_futures_um_trades RENAME TO raw_futures_um_trades_bad;`
3. `ALTER TABLE crypto.raw_futures_um_trades_old RENAME TO raw_futures_um_trades;`
4. 验证：`\\d+` + 抽样 `COUNT(*)`。

> 注意：回滚后保留 `*_bad` 以便排查（不要直接 DROP）。

