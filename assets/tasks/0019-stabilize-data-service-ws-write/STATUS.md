# STATUS

## State

- Status: Done

## Evidence

- WS 写入观测：`ws.log` 出现按分钟 `WS写入: ... bucket_ts_max=...`
- DB 新鲜度：最新 `bucket_ts` 与当前时间差值维持在 2 分钟内
- daemon 自愈：ws 运行时长持续增长，无周期性自愈重启

## Key Commits

- `fix(data-service): flush ws candles and protect ws rows`
- `chore(init): prefer requirements.lock.txt`

