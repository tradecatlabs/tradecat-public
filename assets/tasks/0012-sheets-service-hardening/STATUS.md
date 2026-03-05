# STATUS

状态：Done

最后更新：2026-03-05

## 交付点

- `prune_tabs` 调度化：minimal schema 下默认 6h 节流；keep 集合变更会绕过节流立即执行；meta 落在 `local_meta.json`（`prune_tabs_last_epoch/prune_tabs_keep_hash/prune_tabs_last_error`）。
- `SaSheetsWriter._exec` 读请求弱网重试：覆盖 `SSLError/ConnectionResetError/socket.timeout/5xx/429` 等瞬断（读是幂等，允许有限重试）。
- 列宽固化 CLI：新增 `--snapshot-col-widths` 输出 5 行 env（看板/币种查询/Polymarket 三表）；保留历史兼容 `--snapshot-polymarket-col-widths`。
- 日志治理：新增 `SHEETS_LOG_LEVEL=info|debug`；`[DEBUG]` 仅在 debug 输出；daemon 下 prune 产生单行摘要（run/skip + reason + ms + deleted）。

## 证据存证

- 关键提交：
  - `81d96a34`：读请求弱网重试扩展（_exec）
  - `6e0c032c`：prune_tabs 节流加入 keep hash + 默认 6h
  - `6f07021e`：新增 CLI `--snapshot-col-widths`
  - `545a10cf`：日志级别开关 + prune 单行摘要
  - `bd77119d`：README 同步新增 CLI/env
- 门禁：
  - `cd services/consumption/sheets-service && make check`：✅ 通过（pytest：`8 passed`）
  - `cd services/consumption/sheets-service && .venv/bin/python -m src --help`：✅ 包含 `--snapshot-col-widths`
- 代码定位：
  - `rg -n "prune_tabs_keep_hash" services/consumption/sheets-service/src/sa_sheets_writer.py`：✅ 命中（keep hash 落盘/比较）
  - `rg -n "SHEETS_LOG_LEVEL" services/consumption/sheets-service/src/sa_sheets_writer.py services/consumption/sheets-service/src/__main__.py`：✅ 命中（debug gating）

## 未做（P2，可选）

- i18n 缺失键补齐（降噪）
- server Python 升级到 3.12（消除 FutureWarning）
