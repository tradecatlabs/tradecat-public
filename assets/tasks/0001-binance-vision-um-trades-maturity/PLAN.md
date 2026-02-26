# PLAN - 架构决策与落地路径

> 任务编号：0001

## 目标

把 UM trades 采集链路从“能跑”升级为“可审计、可修复、可扩展、成本可控”的业内成熟形态，并且不污染你坚持极简的事实表（`crypto.raw_futures_um_trades`）。

---

## 方案对比（至少两个）

### 方案 A（推荐）：强校验 + storage 审计 + gap repair + v2 字典化（渐进切换）

**做法概览**

1) 下载阶段：为每个 ZIP 下载对应 `.CHECKSUM` 并校验 sha256  
2) 审计阶段：把 `rel_path/size/sha256/batch/error` 全写入 `storage.*`  
3) 治理阶段：`ingest_gaps` 由 repair worker 消费，形成闭环  
4) 成本阶段：新建 v2 表用 `venue_id/instrument_id` 替代 TEXT 主键，减少索引体积与写入放大  

- Pros
  - 可信：从“文件级”建立证据链（对账/替换可识别）
  - 可运维：错误进入结构化表而非只靠日志
  - 可修复：gap 真正闭环（open→closed）
  - 可扩展：v2 降低索引成本，为多 symbol/多交易所铺路
- Cons
  - 工程量更大，需要新增 repair 命令与若干 writer
  - `.CHECKSUM` 格式需先探测（未知即风险点）

### 方案 B：维持现状（Content-Length + ZIP 可打开），仅加点日志

- Pros
  - 代码改动最少
- Cons
  - 不可审计：无法证明数据未被污染/替换
  - 不可修复：gap 只记录，长期缺口不可控
  - 成本问题继续扩大（TEXT 主键索引肥）

**选择**：方案 A。

---

## 逻辑流图（ASCII）

```text
-------------------+        +--------------------------+
 Binance Vision HTTP|        | ccxtpro WS (realtime)    |
-------------------+        +--------------------------+
   ZIP + CHECKSUM            trades stream
        |                         |
        v                         v
  download + sha256 verify     write raw + watermark
        |                         |
        v                         v
   storage.files/import_*      ingest_gaps(open)
        |                         |
        +-----------+-------------+
                    |
                    v
              repair worker
     (consume gaps -> backfill/zip -> ingest -> verify -> close)
```

---

## 原子变更清单（文件/操作级序列，不写代码）

### Phase 0（P0：可信与审计）

1) 下载工具增强（checksum）
   - 修改：`services/ingestion/binance-vision-service/src/runtime/download_utils.py`
   - 新增（可选）：`services/ingestion/binance-vision-service/src/runtime/checksum_utils.py`
   - 行为：支持下载 `.CHECKSUM`、解析、计算本地 sha256、严格对比

2) 回填链路写入 storage 审计
   - 修改：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/trades.py`
   - 引入 writer：`src/writers/storage_files.py`（已有）
   - 新增 writer：`src/writers/import_meta.py`（建议封装 `storage.import_batches/import_errors/file_revisions`）

### Phase 0（P0：缺口修复闭环）

3) 新增 repair 命令/入口
   - 修改：`services/ingestion/binance-vision-service/src/__main__.py`（新增 `repair` 子命令）
   - 新增：`services/ingestion/binance-vision-service/src/collectors/crypto/repair/futures/um/trades.py`
   - 行为：扫描 `crypto.ingest_gaps(status='open')` → 下载/回填 → 对账通过 → 更新 gap 状态

### Phase 1（P1：成熟成本结构）

4) v2 表（字典化维度键）
   - DB：在 `crypto` 下新建 `raw_futures_um_trades_v2`
   - 依赖：`core.venue/core.instrument/core.symbol_map`
   - 兼容：提供 view 输出 `exchange/symbol`（对学习向与现有查询友好）
   - 切换：通过开关实现“先双写→再只写 v2”

---

## 回滚协议（100% 还原现场）

> 目标：任何一步失败都能快速回到“旧链路仍可跑”的状态。

1) checksum 强校验引发大面积失败
   - 临时回滚：提供 `--allow-no-checksum` 或 env 开关，恢复为“可跑但不可信”模式
   - 同时要求：所有跳过校验的文件必须标记 `storage.files.meta.unverified=true`

2) repair worker 导致误修复/重复写入
   - 停止 repair 命令（不影响 realtime/backfill）
   - 将 gap status 设置为 `ignored`（避免反复消费）

3) v2 切换导致查询/写入异常
   - 立即切回只写 v1（保留 v2 表但不写）
   - v2 作为旁路实验表保留，等验收通过再启用
