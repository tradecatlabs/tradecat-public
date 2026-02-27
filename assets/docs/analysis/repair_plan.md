# 修复任务详细规划（Binance 数据链路）

> 目标：对齐 Tradecat Preview / Pro1 的期货指标 API 与真实表结构，修复 OI/FR/metrics/OHLC 的表映射、时间列与 exchange 过滤，完成可验证的接口一致性。

---

## 1. 修复范围

- 仅限 API 层查询逻辑与参数一致性
- 不改 DB 架构、不改生产配置
- 影响服务：
  - tradecat/services/consumption/api-service
  - new/tradecat-pro1/control/preview/api-service

---

## 2. 目标与验收标准

- OI/FR/metrics 在 5m/15m/1h/4h/1d/1w 使用正确表名
- _last 表使用 bucket 时间列，5m 使用 create_time
- 所有接口按 exchange 过滤（避免多交易所混表污染）
- interval 白名单与表映射一致
- Pro1 的 OHLC 按 interval 读取正确表

验收：
- curl 验证返回 success=true 且 data 长度 > 0
- 1h 不再报 "metrics_1h does not exist"

---

## 3. 任务清单（状态）

### 已完成
- 更新 OI/FR 表映射为 binance_futures_metrics_*_last（preview/pro1）
- 修正 _last 表时间列为 bucket（preview/pro1）
- 修正 Pro1 OI/FR interval 白名单与表映射
- 修正 Pro1 OI/FR 增加 exchange 过滤
- 修正 preview/pro1 metrics：表映射 + bucket/create_time + exchange 过滤
- 修正 Pro1 OHLC：按 interval 映射表 + exchange 过滤

### 待执行
- 重启 API 服务并回归验证
- 记录修复验证结果（保留命令与输出摘要）

---

## 4. 执行步骤（按顺序）

1) 重启服务
   - tradecat api（本仓库）:
     - cd services/consumption/api-service
     - ./scripts/start.sh restart

2) 回归验证（关键接口）
   - OI/FR 1h：
     - curl -sS "http://127.0.0.1:8088/api/futures/open-interest/history?symbol=BNB&interval=1h&limit=200"
     - curl -sS "http://127.0.0.1:8088/api/futures/funding-rate/history?symbol=BNB&interval=1h&limit=200"
   - metrics 1h：
     - curl -sS "http://127.0.0.1:8088/api/futures/metrics?symbol=BNB&interval=1h&limit=200"
   - OHLC 1h（Pro1 验证仅当服务启动）：
     - curl -sS "http://127.0.0.1:8088/api/futures/ohlc/history?symbol=BNB&interval=1h&limit=200"

3) 记录结果
   - 保存响应摘要（success/data 长度/错误码）
   - 如失败：记录具体错误与表名

验证结果（2026-01-28）
- OI 1h: 失败，错误 "column exchange does not exist"
- FR 1h: 失败，错误 "column exchange does not exist"
- Metrics 1h: 失败，错误 "column exchange does not exist"

结论：_last 表缺失 exchange 字段，当前过滤条件不匹配。
待修复：对 _last 表采用无 exchange 过滤的降级策略（保留 5m 的 exchange 过滤）。

复验结果（2026-01-28，修复后）
- OI 1h: success=true, rows=200
- FR 1h: success=true, rows=200
- Metrics 1h: success=true, rows=200

---

## 5. 变更清单（文件）

- services/consumption/api-service/src/routers/open_interest.py
- services/consumption/api-service/src/routers/funding_rate.py
- services/consumption/api-service/src/routers/futures_metrics.py
- $LEGACY_TRADECAT_PRO1_ROOT/control/preview/api-service/src/routers/open_interest.py
- $LEGACY_TRADECAT_PRO1_ROOT/control/preview/api-service/src/routers/funding_rate.py
- $LEGACY_TRADECAT_PRO1_ROOT/control/preview/api-service/src/routers/futures_metrics.py
- $LEGACY_TRADECAT_PRO1_ROOT/control/preview/api-service/src/routers/ohlc.py

> 历史参考（源仓库路径，当前仓库目录已迁移并移除 `services-preview/`）：
> - $LEGACY_TRADECAT_ROOT/services-preview/api-service/src/routers/{open_interest,funding_rate,futures_metrics}.py

---

## 6. 风险与回滚

- 风险：若 _last 表不存在或无 exchange 字段，会导致返回空数据
- 回滚：恢复原表名映射与查询条件（按 git diff 反向修改）

---

## 7. 后续优化（可选）

- 为 /metrics 增加可选 startTime/endTime
- 对 indicator/data 增加排序字段（稳定返回最新）
- 文档同步：将 interval/表映射写入 references/endpoints.md
