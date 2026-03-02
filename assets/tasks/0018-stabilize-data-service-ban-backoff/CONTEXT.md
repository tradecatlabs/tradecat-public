# CONTEXT（现状、证据、风险与假设）

## 1) 现状追溯（仓库事实 + 证据）

### 1.1 418 ban 以“网络错误”形式出现，但未进入全局 ban 冷却

- `services/ingestion/data-service/src/adapters/ccxt.py:114-126`：
  - 仅 `ccxt.RateLimitExceeded` 分支会对 `418` 调用 `parse_ban()` + `set_ban()`。
- `services/ingestion/data-service/src/adapters/ccxt.py:127-131`：
  - `NetworkError/ExchangeNotAvailable/RequestTimeout` 分支只记录 `fetch_ohlcv 网络错误` 并返回/重试，**不会** `parse_ban()`/`set_ban()`。

证据（日志）表明 418 ban 正在走“网络错误”分支：

- `services/ingestion/data-service/logs/ws.log` 中多次出现：
  - `adapters.ccxt - fetch_ohlcv 网络错误: binance 418 I'm a teapot ... IP banned until ...`（可用 `rg -n "418 I'm a teapot|IP banned" services/ingestion/data-service/logs/ws.log | tail` 复核）

这意味着：即便 limiter 已具备跨进程 ban 文件共享（`services/ingestion/data-service/src/adapters/rate_limiter.py:15-76`），在 418 走 `NetworkError` 的情况下也无法生效。

### 1.2 WS 自愈依赖 DB 新鲜度，遇到 ban 会被反复触发（重启风暴）

- `services/ingestion/data-service/scripts/start.sh:103-113`：
  - ws DB 自愈阈值默认：`STALE_MAX_AGE=240s`，`CONSECUTIVE=3`，`WARMUP=300s`
- `services/ingestion/data-service/scripts/start.sh:399-434`：
  - 当 `candles_1m` 最新时间距现在超过阈值，连续多次即 `stop_component ws` + `start_component ws`。
- `services/ingestion/data-service/logs/daemon.log`：
  - 大量 `ws DB 新鲜度陈旧...` → `ws DB 连续陈旧，执行自愈重启 ws...`（可用 `rg -n "ws DB 新鲜度陈旧|执行自愈重启" ... | head/tail` 复核）

问题：ban 期间 DB 不写入是“外部限制导致的合理结果”，重启 ws 并不能解除 ban，反而会：

1) 放大启动阶段的补齐与巡检（更多 REST 请求）
2) 加剧资源占用与日志噪声
3) 拉长恢复时间

### 1.3 REST backfill 默认并发过高，容易触发“请求权重过量”

- `services/ingestion/data-service/src/collectors/backfill.py:137-188`：
  - `RestBackfiller(workers: int = 8)`，并行补齐缺口。
- `services/ingestion/data-service/src/collectors/backfill.py:151-164`：
  - 单个 gap 填充内包含循环分页，多次调用 `fetch_ohlcv(...)`。
- `services/ingestion/data-service/src/adapters/ccxt.py:110-133`：
  - `fetch_ohlcv` 每次尝试前都会 `acquire(2)`，在并发下很容易消耗请求权重。

注意：`MetricsRestBackfiller` 已正确处理 418/429 并 `set_ban()`（`services/ingestion/data-service/src/collectors/backfill.py:205-216`），但 `RestBackfiller` 依赖的 `fetch_ohlcv` 目前对 418 的识别不完整（见 1.1）。

---

## 2) 目标行为（What “Good” Looks Like）

1) 一旦出现 418/429/ban：
   - 全进程共享 ban（通过 `.ban_until`），所有 acquire 都会等待，不再继续打满 REST。
2) ban 期间：
   - ws 自愈不得频繁重启（至少要能识别“处于 ban 冷却中”，选择跳过或延后重启）。
3) 恢复后：
   - 采集/补齐能自动续跑，不需要人工介入。

---

## 3) 风险量化表（Risk Map）

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| ban 识别不全导致持续 418 | High | `ws.log` 持续出现 418；`rate_limiter` 无 `IP ban 至` | 统一异常分支都做 `maybe_set_ban()` |
| 自愈重启放大故障 | High | `daemon.log` 大量重启 ws；CPU/IO 飙升 | 自愈逻辑在 ban/REST 故障时降级 |
| backfill 并发导致权重爆表 | Medium | 频繁 429/418；ban 时间不断延长 | workers 可配置 + 默认收敛 + 请求权重调整 |
| 误判 ban 造成长时间停摆 | Medium | 明显无 418 但仍等待 | 仅在明确命中 418/429/ban msg 时 set_ban，并输出触发源 |

---

## 4) 假设与证伪（Safe-Inference）

> 原则：信息不全时，先写最保守假设，并给出可执行命令证伪。

1) 假设：`418 I'm a teapot` 在当前 ccxt 版本里会被归类为 `ccxt.NetworkError`（至少在本仓库运行形态下如此）。  
   - 证伪命令：`rg -n "418 I'm a teapot" services/ingestion/data-service/logs/ws.log | head`
2) 假设：`start.sh` 的 ws 自愈依据为 `market_data.candles_1m` 的最新时间。  
   - 证伪命令：`rg -n "candles_1m" services/ingestion/data-service/scripts/start.sh`
3) 假设：ban 共享文件为 `services/ingestion/data-service/logs/.ban_until`。  
   - 证伪命令：`ls -la services/ingestion/data-service/logs/.ban_until* || true`

