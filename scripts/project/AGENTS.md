# tradecat Agent 操作手册

本文件作用域：`tradecat-public/scripts/project/**`。

## 使命

`tradecat-public` 是一个 multi-Agent Skill 包装仓库；真实 TradeCat 用户侧消费端项目位于 `scripts/project/`。该项目只读公开在线表格，把数据保存为本地快照缓存文件，并提供轻量 CLI / TUI 浏览能力；也提供零安装的一次性请求脚本。

## 禁区

- 禁止连接或写入 TradeCat 服务端 PostgreSQL。
- 禁止把该服务接入服务端数据生产链路。
- 禁止重新引入 SQLite、本地 SQL 查询层或数据库型后端存储。
- 禁止依赖 `apps/sheets` 内部实现细节；只能依赖公开在线表格 CSV 契约。
- 禁止把缓存文件、凭证、Google key、私密 `.env` 写入仓库。

## 目录结构

```text
tradecat-public/
├── README.md
├── AGENTS.md
├── lessons.md
├── SKILL.md
├── agents/
│   ├── manifest.json
│   ├── hermes.yaml
│   └── openai.yaml
├── references/
│   ├── agent-contract.md
│   ├── agent-contract-maturity-task-tree.md
│   ├── agent-contract-maturity-task-tree.json
│   ├── agent-readiness-remediation-task-tree.md
│   ├── agent-readiness-remediation-task-tree.json
│   ├── architecture.md
│   ├── cache-contract.md
│   ├── first-run-cache.md
│   ├── index.md
│   ├── install-uninstall.md
│   ├── linear-flows.md
│   ├── quality-gate.md
│   ├── release.md
│   ├── stability-hardening-task-tree.md
│   ├── stability-hardening-task-tree.json
│   └── tui-contract.md
└── scripts/
    ├── validate-skill.sh
    ├── bootstrap-dev.sh
    ├── security-scan.sh
    ├── supply-chain-audit.sh
    ├── install-security-tools.sh
    ├── clean-local-runtime.sh
    ├── agent-smoke.sh
    ├── run-tradecat.sh
    ├── verify.sh
    └── project/
        ├── README.md
        ├── AGENTS.md
        ├── DEBUG.md
        ├── DEBUG.archive.md
        ├── install.sh
        ├── install.ps1
        ├── uninstall.sh
        ├── uninstall.ps1
        ├── Makefile
        ├── constraints.txt
        ├── contracts/
        ├── pyproject.toml
        ├── scripts/
        │   ├── guard_public_local_files.sh
        │   ├── request.py
        │   ├── start.sh
        │   ├── validate_data_contract.py
        │   ├── verify.sh
        │   └── watchdog.sh
        ├── src/
        │   └── tradecat_terminal/
        │       ├── __init__.py
        │       ├── __main__.py
        │       ├── cache.py
        │       ├── cli.py
        │       ├── contracts.py
        │       ├── config.py
        │       ├── dataset_registry.json
        │       ├── diagnostics.py
        │       ├── header_aliases.py
        │       ├── i18n.py
        │       ├── lifecycle.py
        │       ├── migrations.py
        │       ├── registry.py
        │       ├── service_entry.py
        │       ├── settings.py
        │       ├── sheets.py
        │       ├── state.py
        │       ├── structured_cache.py
        │       ├── sync.py
        │       ├── tui.py
        │       ├── view_model.py
        │       └── runtime/
        │           └── paths.py
        └── tests/
            ├── fixtures/
            │   └── json_contract/
            ├── test_agent_contract.py
            ├── test_cache_tui.py
            ├── test_exit_codes.py
            ├── test_json_contract.py
            ├── test_payload_schema_validation.py
            └── test_transport.py
```

## Linear Flow

### Flow 1: 在线表格到本地快照缓存

```text
Input(输入)：公开 Google Sheets CSV、dataset registry、本地 cache_dir
-> 节点1：`cli.py` / `lifecycle.py` 接收 `sync/probe/watch` 命令并解析缓存目录
-> 节点2：`registry.py` 从 `dataset_registry.json` 加载 workbook、tab、gid、dataset_key 与 data_mode
-> 节点3：`sheets.py` 通过成熟 HTTP retry/backoff/jitter 拉取 CSV，并把网络失败分类成 typed error
-> 节点4：`migrations.py` 在写入前检查缓存 metadata schema，必要时先备份再迁移
-> 节点5：`cache.py` 在 `state.py` 文件锁保护下按 matrix hash 写入 snapshot 文件；hash 不变则跳过新增文件
-> 节点6：`cache.py` 对 `event_stream` 额外按 event_key 与 normalized_event_key 合并 `stream_events.json`
-> 节点7：`structured_cache.py` 生成固定结构化文件 `latest.json` / `latest.jsonl` / `latest.csv` 和根 `manifest.json`
-> Output(输出)：可由 TUI、用户脚本和 Agent 读取的本地结构化快照缓存
```

### Flow 2: 本地缓存到 TUI 展示

```text
Input(输入)：用户 TUI 请求、本地 cache_dir、dataset registry、语言参数或 `TRADECAT_LANG`
-> 节点1：`cli.py` / `tui.py` 解析 TUI 参数、缓存目录和语言；`i18n.py` 翻译 UI 外壳文案
-> 节点2：`settings.py` 提供默认语言、默认 tap、缓存目录和探针间隔；环境变量仍可临时覆盖
-> 节点3：`tui.py` 先读取本地缓存并打开界面，不在启动前阻塞式拉取远端
-> 节点4：`cache.py` 切分广告/链接/元信息区、业务表头和业务数据区，保留物理列与原始字段
-> 节点5：`view_model.py` 输出物理列 A/B/C... 供 TUI 渲染，同时在 `column_meta` 保留 raw/display/physical 三层字段元数据
-> 节点6：`tui.py` 按真实内容宽度生成整表 psql 视图，不做列冻结或横向列滚动
-> 节点7：`tui.py` 提供帮助页、状态栏、搜索过滤、首尾跳转、选行和链接打开能力
-> 节点8：`tui.py` 在 live 模式下后台 probe 当前 dataset，并按 tap 独立间隔后台保鲜非焦点 active dataset
-> 节点9：远端变化后写入结构化缓存、失效对应 dataset 的内存 view/render cache 并重绘
-> Output(输出)：无后端数据库、无 SQL 的终端表格浏览界面
```

### Flow 3: 零安装一次性请求

```text
Input(输入)：`python3 <(curl .../scripts/project/scripts/request.py) <dataset_key>`、公开 dataset registry JSON、公开 Google Sheets CSV
-> 节点1：`scripts/project/scripts/request.py` 读取 `dataset_registry.json` URL 并解析 format/limit/meta/headers 参数
-> 节点2：`scripts/project/scripts/request.py` 根据共享 registry 生成 Google Sheets CSV export URL，不创建本地缓存，不依赖 Python 第三方库
-> 节点3：脚本解析顶部信息、表头和业务行
-> Output(输出)：table/json/jsonl/csv/raw/stdout，一次性返回给用户、shell 或 Agent
```

### Flow 4: 用户一键安装

```text
Input(输入)：`curl .../scripts/project/install.sh | sh` 或 `irm .../scripts/project/install.ps1 | iex`
-> 节点1：安装脚本解析安装目录、bin 目录、仓库地址、分支/ref 与 Python 版本环境变量
-> 节点2：安装脚本克隆或更新公开仓库到用户目录；设置 `TRADECAT_INSTALL_REF` 时固定 checkout 指定 tag/ref
-> 节点3：安装脚本优先使用本机 Python 3.12；缺失时尝试安装 uv 并由 uv 创建 Python 3.12 虚拟环境
-> 节点4：安装脚本定位仓库内 `scripts/project/` 项目目录，创建 `.venv` 并执行 editable install
-> 节点5：安装脚本写入用户级 `tradecat` / `tcat` launcher；branch 安装默认按节流规则后台更新安装仓库，`TRADECAT_FORCE_UPDATE=1` 时阻塞更新；固定 ref 安装不自动更新
-> 节点6：安装脚本写入用户级 `tradecat-uninstall` / `tcat-uninstall` launcher
-> 节点7：安装脚本设置 `TRADECAT_NO_AUTO_UPDATE=1` 执行 `tradecat init`，best-effort 执行 `tradecat sync-all`；全量同步失败时兜底同步 `event_stream`
-> Output(输出)：用户可在任意目录运行 `tradecat`，也可运行 `tradecat-uninstall` 卸载
```

### Flow 5: 用户智能卸载

```text
Input(输入)：`tradecat-uninstall`、`curl .../scripts/project/uninstall.sh | sh` 或 `irm .../scripts/project/uninstall.ps1 | iex`
-> 节点1：卸载脚本解析安装目录、bin 目录、运行态目录和 `TRADECAT_KEEP_CACHE`
-> 节点2：如果 `TRADECAT_KEEP_CACHE=1`，卸载脚本优先把 `scripts/project/.tradecat/cache` 移动到用户目录备份；旧布局缓存作为兼容回退
-> 节点3：卸载脚本删除 `tradecat` / `tcat` / `tradecat-uninstall` / `tcat-uninstall` 命令入口
-> 节点4：卸载脚本删除 TradeCat 安装目录与后台 watch 运行态目录
-> Output(输出)：TradeCat 本体被卸载；系统 Python、git、uv 与用户 PATH 不被删除
```

### Flow 6: 本地配置与视图导出

```text
Input(输入)：`tradecat config ...` 或 `tradecat export <dataset_key>`
-> 节点1：`cli.py` 解析 config/export 命令、缓存目录、输出格式和语言参数
-> 节点2：`settings.py` 读写本地 `.tradecat/settings.json`，只保存用户偏好，不保存远端数据
-> 节点3：`view_model.py` 从本地缓存构造显示模型，保留 display/raw/physical 三层字段
-> 节点4：`cli.py` 按 json/jsonl/csv/table 输出当前缓存视图；csv/jsonl 使用原始字段，table 保持物理列 A/B/C... 与原始表头行
-> Output(输出)：可供用户、shell 和 Agent 消费的配置状态或视图导出结果
```

### Flow Rules

- 节点数量必须刚好覆盖真实主链路。
- 不允许省略必要节点。
- 不允许添加不存在的伪节点。
- 每个节点必须能追溯到代码、脚本、配置、数据表、接口或文档。
- 架构、目录、入口、数据流或控制流变化时，必须同步更新本流程。

## 模块职责

以下路径除特别说明外，均以 `scripts/project/` 为项目根目录。

- `cache.py`：本地 JSON 快照缓存引擎；负责 manifest、snapshot、event stream 去重、显式 prune、可选 gzip 和 typed sync error 输出。
- `cli.py`：命令行入口，只做参数解析与流程编排。
- `contracts.py`：CLI JSON `schema/schema_version` 与稳定 error object 契约层。
- `constraints.txt`：运行与开发依赖锁定口径；安装器、CI 和本地 bootstrap 都必须消费。
- `config.py`：本地缓存目录与环境变量解析；默认缓存根为项目根 `scripts/project/.tradecat/cache`。
- `dataset_registry.json`：workbook、dataset、gid、tab、显示名、探针间隔和数据模式的单一真相源。
- `diagnostics.py`：本地诊断与 support bundle 层；只记录公开安全的错误摘要、环境摘要和缓存水位。
- `header_aliases.py`：字段别名元数据层；只进入 ViewModel 的 `column_meta.display_name`，禁止替代 TUI 表格物理列 A/B/C...
- `i18n.py`：TUI/CLI 外壳文案的轻量多语言表；只处理中文、英文、韩语 UI 文案。
- `install.sh`：POSIX 一键安装入口，覆盖 Linux / macOS / WSL / Git Bash。
- `install.ps1`：Windows PowerShell 一键安装入口。
- `lifecycle.py`：用户侧 ensure / probe / watch 生命周期闭环；`doctor --fix` 只修复本地目录骨架，`doctor --repair` 只修本地 metadata，二者都不隐式触发远端同步。
- `migrations.py`：缓存 metadata schema 迁移层；所有迁移必须幂等、备份、可回滚。
- `registry.py`：从 `dataset_registry.json` 加载 workbook、tab、dataset、data_mode、TUI 探针间隔与多语言展示名。
- `scripts/request.py`：零安装一次性公开数据请求脚本；公开 curl 路径为 `scripts/project/scripts/request.py`；读取共享 registry，只能用标准库，JSON 模式必须输出 `tradecat.request_result.v1`。
- `scripts/validate_data_contract.py`：公开 dataset registry 与 Google Sheets CSV 契约校验入口；CI 可用 `--remote` 做公网 smoke。
- `tests/fixtures/json_contract/`：Agent JSON 契约 golden 样本；只保存脱敏、稳定、可 schema 校验的最小 payload。
- `tests/test_payload_schema_validation.py`：真实 CLI/request payload 与 golden fixtures 的 JSON Schema 校验门禁；只能依赖 dev/test 依赖，不能把 `jsonschema` 带入运行时依赖。
- `settings.py`：用户侧本地配置文件读写；管理默认语言、默认 tap、缓存目录和探针间隔，写入必须原子化并保留 `.bak`。
- `sheets.py`：Google Sheets CSV 只读拉取与 matrix 解析；网络层使用 `urllib3` retry/backoff/jitter 和 typed error。
- `state.py`：本地文件锁与原子写基础设施；跨平台锁只能通过此模块集中使用。
- `structured_cache.py`：结构化缓存投影层；负责 `latest.json` / `latest.jsonl` / `latest.csv` / 根 manifest。
- `sync.py`：缓存同步入口薄封装。
- `tui.py`：终端浏览入口；只读缓存文件，使用后台探针、内存 view/render cache 与显示宽度感知 psql 风格渲染器。
- `uninstall.sh`：POSIX 智能卸载入口，删除安装目录、launcher 和运行态目录，支持保留缓存。
- `uninstall.ps1`：Windows PowerShell 智能卸载入口。
- `view_model.py`：TUI 显示模型层；把结构化缓存投影为显示列、原始列、物理列和链接语义。
- `runtime/`：用户本地运行态路径，不写仓库源码树。

## 修改规则

- 新能力必须保持自包含，不能反向依赖 TradeCat 服务端运行环境。
- CLI / TUI 的唯一运行态数据源是本地 JSON 快照缓存。
- 禁止重新引入 `db.py`、`query.py`、SQLite schema、SQL 示例或数据库 vacuum/compress 维护命令。
- `sync/probe/watch` 只能写 `TRADECAT_CACHE_DIR` 下的缓存文件；未设置时固定写项目根 `scripts/project/.tradecat/cache`。
- 每次写入 dataset 缓存必须同步生成 `latest.json`、`latest.jsonl`、`latest.csv`；禁止只写原始 snapshot 而不更新结构化投影。
- 每次写缓存、manifest、stream state 或 settings 必须使用 `state.py` 文件锁和原子替换；禁止各模块自行发明锁语义。
- 远端 CSV 拉取失败必须输出稳定 error code/kind/hint/retryable，禁止上层继续依赖 `str(exc)` 猜错误类型。
- Agent 广告的 JSON 输出必须带 `schema` 和 `schema_version`；失败时 `error` 必须是对象，不能退化成自由文本。
- 单次 dry-run probe 的 `tradecat.probe_result.v1` 是正式 Agent 契约；watcher 生命周期控制面（`start.sh status/start/stop --json` 与 `watchdog.sh --json`）的 `tradecat.watch_status.v1` 是正式 Agent 契约；`restart --json` 只给 operator 使用，不写成 Agent 首选入口；`tradecat.watch_cycle.v1` 长期保持内部长运行契约，未被未来任务正式提升前不得写成 Agent 正式承诺面。
- cache schema 变更必须走 `migrations.py`，并补 fixture 回归；禁止临时 if/else 隐式升级历史缓存。
- snapshot dataset 必须按完整 CSV matrix hash 决定是否新增快照文件。
- `event_stream` 必须独立按事件键增量合并，重复事件只能更新 `seen_count / last_seen_at`。
- TUI 默认 live 模式当前焦点 dataset 走前台后台线程 probe；非焦点 active dataset 也必须按独立间隔后台保鲜。
- 无参数 `tradecat` 默认 dataset 是 `event_stream`。
- 用户偏好必须通过 `settings.py` 写入本地 JSON；环境变量只作为更高优先级的临时覆盖。
- `tradecat export` 必须只读本地缓存，不得触发远端网络请求。
- export 的 `csv/jsonl` 必须保留原始字段；`table` 必须保持物理列 A/B/C... 与原始表头行，方便对照在线表格。
- TUI 探针间隔必须支持 dataset 独立配置；`event_stream` 默认 3.0s，其它 tap 默认 10s。
- 单 tap 环境变量 `TRADECAT_TERMINAL_<DATASET_KEY>_TUI_PROBE_INTERVAL` 优先于全局 `TRADECAT_TERMINAL_TUI_PROBE_INTERVAL`，命令行 `--probe-interval` 优先级最高。
- TUI fetch timeout 必须支持 dataset 独立配置；`event_stream` 默认 3.0s，其它 tap 默认 2.0s，且 timeout 不得超过当前基础 interval。
- TUI 高频探针必须有连续失败退避：1 次失败不低于 3s，2 次不低于 5s，3 次及以上不低于 15s，成功后恢复基础 interval。
- TUI 启动必须 cache-first，禁止在进入界面前阻塞式 probe。
- TUI live probe 必须后台化；禁止在 curses 主循环内同步拉远端 CSV。
- TUI 滚动、选行、hover、鼠标移动路径不得重复读取 JSON 快照或重建无关 tap 的视图。
- TUI 帮助页必须由 `?` 打开/关闭，不能要求用户读 README 才能知道基础热键。
- TUI 搜索过滤必须只影响当前视图，不得改写缓存文件。
- TUI 状态栏必须持续暴露缓存状态、远端导出时间、本地拉取时间、探针状态、下次刷新和缓存路径。
- `event_stream` 必须保持轻量渲染，只渲染时间与内容两列，禁止把长文本流按宽表路径完整重算。
- TUI 必须处理 `KEY_RESIZE` 与无按键时的终端尺寸变化；窗口或字体缩放后要立即失效 render cache 并重绘。
- TUI 左右键必须切换 tap；禁止重新引入主键列冻结或右侧列横向滚动。
- TUI 表格渲染必须按真实内容宽度生成 psql 表格，禁止按 tap 做自动缩放、撑满空隙或固定宽度省略。
- Windows / Web SSH / 无 curses fallback 必须使用 Rich 无边框限宽 plain renderer；禁止在 fallback 中输出 psql 长边框。
- TUI 表格区保留在线表格物理列 A/B/C...、原始行号和表格内业务表头行；禁止用业务字段别名替代顶层列字母。
- TUI 多语言允许作用于外壳文案、操作提示、状态行、fallback 提示和 dataset 展示名；禁止修改 TUI 表格列字母、远端原始列名、单元格内容、JSON key、CSV header 或 dataset_key。
- TUI 语言必须支持 `zh` / `en` / `ko`，优先级为 `--lang`、`TRADECAT_LANG`、系统 locale、默认 `zh`；交互内用 `l/L` 循环切换。
- 超长单元格由终端视口裁剪；要看全依赖扩大终端列数或缩小终端字体，缓存文件必须保留完整值。
- 鼠标 hover/click 交易对必须基于可见交易对单元格，不得整行跳转。
- 鼠标 hover/click URL 文本必须直接打开 URL；URL 优先级高于交易对推断。
- 历史快照默认永久保留；裁剪只能通过 `tradecat prune --apply` 显式触发。
- `TRADECAT_CACHE_COMPRESSION` 默认必须保持 `none`；gzip 只能作为新快照的可选模式。
- 后台运行只允许管理用户本地 `watch` 进程，不得接入 TradeCat 生产进程管理。
- 新增配置、缓存路径、结构化 JSON 字段或公开请求参数必须同步更新 `scripts/project/README.md`。
- `scripts/project/scripts/request.py` 是公开 curl 入口，必须保持无第三方依赖、无本地写入、无私密源，并且 dataset/workbook/gid 必须来自共享 `dataset_registry.json`。
- `install.sh` 必须保持 POSIX `sh` 兼容，禁止依赖 bash-only 语法。
- `install.ps1` 是 Windows 原生入口；不要承诺 `curl ... | sh` 能覆盖原生 PowerShell。
- `install.sh` / `install.ps1` 默认安装稳定 tag；只有显式 `TRADECAT_INSTALL_BRANCH=develop` 这类分支通道安装才让 `tradecat` / `tcat` launcher 按 `TRADECAT_UPDATE_INTERVAL_SECONDS` 后台自动更新安装仓库；`TRADECAT_NO_AUTO_UPDATE=1` 跳过，`TRADECAT_FORCE_UPDATE=1` 改为阻塞更新且失败直接退出。
- 安装脚本写 launcher 时必须替换 `TRADECAT_BIN_DIR` 下已有旧文件或失效 symlink，禁止跟随旧 symlink 写入已不存在的开发虚拟环境。
- 启动前自动更新只能发生在 launcher 层，禁止在 `cli.py` / `tui.py` 导入业务模块后再修改源码。
- 安装过程执行 `tradecat init` / `tradecat sync-all` / `tradecat sync event_stream` 时必须临时设置 `TRADECAT_NO_AUTO_UPDATE=1`，避免安装链路重复自更新；`sync-all` 失败后必须兜底同步默认 `event_stream`。
- `install.sh` / `install.ps1` 必须写入本地短命令 `tradecat-uninstall`。
- `uninstall.sh` / `uninstall.ps1` 禁止删除系统 Python、git、uv 或用户 PATH；只能删除 TradeCat 安装目录、launcher 和运行态目录。
- 架构或目录变化必须同步更新 `SKILL.md`、`references/` 与本文件。

## 验证

```bash
python3 -m compileall src tests
pytest -q
PYTHONPATH=src python3 scripts/validate_data_contract.py --remote --timeout 10
bash scripts/verify.sh
bash ../../scripts/security-scan.sh
bash ../../scripts/supply-chain-audit.sh
```

## 本地命令入口

- `pyproject.toml` 必须保留 `tradecat` / `tradecat-terminal` / `tcat` 三个 console script，其中 `tradecat` 是对外主入口，`tradecat-terminal` 是兼容入口。
- `tradecat` 无参数时必须默认进入 TUI，保持像 `btop` 一样的用户侧启动体验。
- 面向任意目录调用时，允许把 `.venv/bin/tradecat` 软链接到 `~/.local/bin/tradecat`；不得要求用户每次手动 `cd` 到服务目录。
