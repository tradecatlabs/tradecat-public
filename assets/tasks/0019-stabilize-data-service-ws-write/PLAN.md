# PLAN

## 目标

让 `data-service` 的 WS 1m candles：

- **按分钟稳定写入** `market_data.candles_1m`
- DB 最新 `bucket_ts` 始终接近当前时间（age 维持在可控阈值内）
- daemon 不再触发“DB 陈旧 → 自愈重启 ws”
- backfill 仅用于填缺口，不覆盖 WS 行

## 方案对比

### 方案 1：继续依赖 daemon 重启 + REST 补齐（不推荐）

- Pros：实现成本低
- Cons：长期会触发 418/429 ban 风险；稳定性差；WS 价值被抵消

### 方案 2：修复 WS flush + 回调桥接 + backfill 覆盖（采用）

- Pros：最小改动、保持现有架构；可观测；WS 成为主路径；backfill 退回“补洞”
- Cons：需要对写入策略做一次明确的“冲突优先级”约定（WS > backfill）

## 数据流（ASCII）

```text
cryptofeed (CANDLES closed)
  -> adapters/cryptofeed.py (_on_candle)
      -> WSCollector._on_candle (buffer)
          -> _delayed_flush (idle>=window)
              -> TimescaleAdapter.upsert_candles(update_on_conflict=True)
                  -> market_data.candles_1m

Gapfill/Backfill (REST/ZIP)
  -> collectors/backfill.py
      -> TimescaleAdapter.upsert_candles(update_on_conflict=False)
          -> INSERT ONLY (DO NOTHING on conflict)
```

## 回滚策略（Rollback）

- 若发现 backfill 需要覆盖逻辑（例如历史数据修正），可将 `update_on_conflict=False` 改回 True 或引入更细粒度策略（按 source 决策）。
- 若 WS 写入恢复前需要快速止血：保留 daemon 自愈与 backfill，可恢复旧行为（但建议先定位代理/网络问题再回滚）。

