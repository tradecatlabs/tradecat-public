# AI 分析服务

telegram-service 的子模块，提供基于 LLM 的加密货币市场深度分析。

## 目录结构

```
ai-service/
├── src/
│   ├── __init__.py         # 模块入口
│   ├── config.py           # 配置
│   ├── pipeline.py         # 分析管道
│   ├── bot/handler.py      # Telegram 交互
│   ├── llm/client.py       # LLM 客户端
│   ├── data/fetcher.py     # 数据获取
│   └── prompt/             # 提示词管理
├── prompts/                # 提示词文件
├── scripts/start.sh        # 测试脚本
└── requirements.txt
```

## 数据流

```
Telegram 用户 → bot/handler.py (币种/周期选择)
             → pipeline.py
             → data/fetcher.py (TimescaleDB + PG(tg_cards))
             → prompt/builder.py
             → llm/client.py (Gemini CLI)
             → 返回分析结果
```

## 在 telegram-service 中集成

```python
# telegram-service/src/bot/app.py
import sys
from pathlib import Path

# 添加 ai-service 路径
AI_SERVICE = Path(__file__).parents[3] / "ai-service"
sys.path.insert(0, str(AI_SERVICE))

from src import register_ai_handlers

# 在 Application 初始化后注册
register_ai_handlers(application, symbols_provider=get_active_symbols)
```

## 测试命令

```bash
# 就绪检查（非独立进程）
./scripts/start.sh start
./scripts/start.sh status
./scripts/start.sh stop

# 检查依赖
./scripts/start.sh check

# 测试数据获取
./scripts/start.sh test BTCUSDT

# 运行分析
./scripts/start.sh analyze BTCUSDT 1h 市场全局解析

# 列出提示词
./scripts/start.sh prompts
```

## 添加新提示词

1. 在 `prompts/` 目录创建 `.txt` 文件
2. 文件名即为提示词名称
3. 重启服务自动加载
