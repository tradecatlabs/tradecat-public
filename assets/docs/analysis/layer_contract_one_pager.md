# 分层契约（一页纸）

> 生成时间: 2026-02-10  
> 目标: 将系统强制收敛为 3 层（采集 / 处理 / 消费），并用“契约”替代口头约定。

---

## 0. 全局约束（适用于所有层）

- **统一时间**：所有时间戳使用 UTC；严禁本地时区混入存储与接口。
- **单一真相源**：PostgreSQL 作为权威数据源；SQLite 仅允许作为消费侧缓存（可丢、可重建）。
- **单向依赖**：采集 → 处理 → 消费；禁止反向调用与跨层写入。
- **至少一次（At-least-once）交付**：允许重复写入，但必须通过幂等键实现“重复无害”。

---

## 1) 采集层（Ingestion）

1. **输入/输出 schema**
   - 输入：`(source, instruments[], intervals[], start_ts, end_ts, auth/config)` + 运行参数（并发、速率、重试上限）
   - 输出（写 PG 的“原始层”）：统一成“带元信息的原始事件/快照”
     - `raw_candles`: `{source, venue, symbol, interval, open_ts, close_ts, o,h,l,c,v, ingest_ts, quality_flags, payload_hash}`
     - `raw_ticks|raw_orderbook|raw_trades`: `{source, venue, symbol, ts, payload_json, ingest_ts, payload_hash}`
     - `raw_prediction_market`: `{source, market_id, ts, payload_json, ingest_ts, payload_hash}`
     - `raw_onchain_events`: `{source, chain, address, tx_hash, log_index, ts, payload_json, ingest_ts, payload_hash}`

2. **幂等键（Idempotency Key）**
   - K 线：`(source, venue, symbol, interval, open_ts)` 唯一（upsert）
   - 预测市场快照：`(source, market_id, ts)` 唯一（upsert）
   - 链上事件：`(source, chain, tx_hash, log_index)` 唯一（insert ignore / upsert）
   - 通用兜底：`payload_hash` 用于重复率统计与异常排查（不作为唯一键的唯一依据）

3. **时间语义（UTC/对齐周期/缺失处理）**
   - 以 `open_ts` 为周期锚点；周期对齐由 `interval` 决定（例如 1m 对齐到分钟边界）
   - 允许“晚到数据”（late arrival）：用 `ingest_ts` 与水位线（watermark）衡量滞后
   - 缺失不补假数据：缺口用 `quality_flags` 标记；是否回填由上层（处理层）策略决定

4. **失败重试策略**
   - 对外请求：指数退避 + 抖动；对 429/限流按 provider 规则降速
   - 对内写库：可重试（基于幂等 upsert）；失败进入“可恢复队列/重试表”（避免无限循环打爆外部源）
   - 熔断：持续错误（例如 5xx/超时）达到阈值后短时间停止该 source 的拉取

5. **可观测性指标（延迟/缺口率/重复率）**
   - 延迟：`now_utc - max(event_ts)`（按 source/venue/symbol/interval 聚合）+ `ingest_lag = ingest_ts - event_ts`
   - 缺口率：期望条数 vs 实际条数（按时间窗/interval 统计）
   - 重复率：upsert 冲突次数 / 总写入次数；`payload_hash` 重复占比

---

## 2) 处理/计算层（Compute）

1. **输入/输出 schema**
   - 输入（读 PG 原始层）：`raw_*` + 维表（币种、交易所、参数集、假期/停牌等）
   - 输出（写 PG 派生层）：指标/特征/信号，均带“可追溯元信息”
     - `features_indicators`: `{indicator_id, params_hash, source_ref, venue, symbol, interval, ts, values_json, compute_ts, input_watermark_ts, quality_flags}`
     - `signals`: `{signal_id, rule_id, context_hash, venue, symbol, ts, severity, payload_json, compute_ts}`
     - （可选）`model_inference`: `{model_id, version, context_hash, ts, payload_json, compute_ts}`

2. **幂等键（Idempotency Key）**
   - 指标点：`(indicator_id, params_hash, venue, symbol, interval, ts)` 唯一（upsert）
   - 信号：`(rule_id, venue, symbol, ts_bucket, context_hash)` 唯一（insert ignore / upsert）
   - 版本隔离：`params_hash` / `model_version` 必须参与幂等键，避免“新算法覆盖旧结果但无法比对”

3. **时间语义（UTC/对齐周期/缺失处理）**
   - 输出 `ts` 与输入周期对齐（与 `open_ts`/`close_ts` 约定必须一致并写入文档）
   - 缺失传播：输入存在缺口时，输出必须在 `quality_flags` 标记（例如 `MISSING_INPUT`, `LATE_INPUT`, `STALE_INPUT`）
   - 窗口类计算：明确“左闭右开/右闭”等边界；并固定在代码与测试中

4. **失败重试策略**
   - 计算任务：天然可重试（确定性、幂等 upsert）；失败按分区（symbol/interval/time window）重跑
   - 外部依赖（如 Pine 转译/模型调用）：必须有超时；失败降级为“跳过并标记 quality_flags”，禁止卡住主流水线
   - 退避与排队：处理层吞吐被压力限制时，优先减小并发而不是扩大重试风暴

5. **可观测性指标（延迟/缺口率/重复率）**
   - 延迟：`compute_lag = compute_ts - input_watermark_ts`；端到端 `e2e_lag = now_utc - ts`
   - 缺口率：指标输出缺口（应有点数 vs 实际点数）；信号触发覆盖率（按规则/币种）
   - 重复率：指标 upsert 冲突率；信号去重命中率（反映幂等键质量）

---

## 3) 消费层（Consumption）

1. **输入/输出 schema**
   - 输入：只读 PG 派生层（`features_indicators`, `signals`, 以及必要的 `raw_*` 只读回查）
   - 输出：面向用户/系统的“投递物”
     - API：`{request_id, ts_range, data[], source_metadata}`
     - 推送：`{channel, dedupe_key, title, body, links[], ts, context}`
     - 缓存（SQLite，允许丢失）：`ui_snapshots`, `rankings`, `last_sent_state`

2. **幂等键（Idempotency Key）**
   - 消息投递：`dedupe_key = (channel, rule_id/indicator_id, venue, symbol, ts_bucket, context_hash)`
   - API 响应不要求幂等写入，但必须带 `request_id` 便于链路追踪
   - 缓存写入必须幂等（同 key 覆盖即可），缓存不可成为业务真相

3. **时间语义（UTC/对齐周期/缺失处理）**
   - 所有对外展示时间统一格式化（但存储/接口仍为 UTC）
   - 展示层可对缺失做“提示”，但不得伪造补齐后的数据点
   - “过期”定义必须清晰：例如 `staleness = now_utc - ts > threshold`

4. **失败重试策略**
   - 对外投递（Telegram/钉钉/飞书/Discord）：指数退避；永久失败进入 DLQ/失败表，避免无限重试
   - 速率限制：按 channel 做全局限流；必要时批量合并（减少 spam）
   - 失败不反向污染上游：消费层失败不应触发重跑采集/计算

5. **可观测性指标（延迟/缺口率/重复率）**
   - 延迟：`delivery_lag = delivered_ts - event_ts`；按 channel 聚合 P50/P95
   - 缺口率：应推送条数 vs 实际推送条数（按规则/币种/时间窗）
   - 重复率：去重命中次数 / 总尝试次数；每 channel 的重复率必须可报警

