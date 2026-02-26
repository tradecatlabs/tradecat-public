# TradeCat 部署执行提示词（给 AI 助手）

> 目标：让 AI 在本机/服务器上 **按仓库现状** 完成初始化、配置与启动，并在最后给出可复核的验证证据。
>
> 约束：不要编造结果；每一步执行后都要检查返回码与关键输出；遇到错误先定位根因再修复。

## 0) 前置假设（可调整，但必须显式说明）

- 当前工作目录为仓库根目录：`/home/lenovo/tradecat/tradecat`
- 你有权限执行 `bash`、`python3`、`make` 等基础命令
- 你不会把任何密钥写入 git（`config/.env` 不提交）

## 1) 初始化（创建各服务虚拟环境 + 安装依赖）

```bash
cd /home/lenovo/tradecat/tradecat
./scripts/init.sh
```

若某个服务依赖安装失败，优先定位对应服务目录的 `requirements*.txt` 与 `Makefile`，并按报错补齐系统依赖（如编译工具链）。

## 2) 配置（生成并填写 `config/.env`）

```bash
cd /home/lenovo/tradecat/tradecat
cp config/.env.example config/.env
chmod 600 config/.env
```

然后编辑 `config/.env`（不要把任何 token/密码写进 README 或提交到 git）：

- `BOT_TOKEN`（Telegram Bot Token）
- 数据库连接（默认 LF=5433、HF=15432）
- 代理（如需要）：`HTTP_PROXY` / `HTTPS_PROXY`

## 3) 启动核心服务

```bash
cd /home/lenovo/tradecat/tradecat
./scripts/start.sh start
./scripts/start.sh status
```

若发现服务未启动或反复崩溃，按提示进入对应服务的 `logs/` 查看日志并修复。

## 4) 验证（必须给出证据）

```bash
cd /home/lenovo/tradecat/tradecat
./scripts/verify.sh
```

验收证据至少包含：

- `./scripts/start.sh status` 输出
- `./scripts/verify.sh` 输出（通过/跳过项的原因）

## 5) 可选：守护进程（自动重启）

```bash
cd /home/lenovo/tradecat/tradecat
./scripts/start.sh daemon
./scripts/start.sh status
```

