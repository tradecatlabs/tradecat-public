# 安装（Getting Started）

> 本页用于满足 `mkdocs.yml` 的导航入口，并提供最短可跑通路径。以仓库脚本为准。

## 环境要求

- Linux/WSL2
- `python3`

## 一键初始化

在仓库根目录执行：

```bash
./scripts/init.sh
```

## 配置

```bash
cp config/.env.example config/.env
chmod 600 config/.env
```

编辑 `config/.env` 填写必要变量（例如 `BOT_TOKEN`、`DATABASE_URL`）。

## 启动

```bash
./scripts/start.sh start
./scripts/start.sh status
```

