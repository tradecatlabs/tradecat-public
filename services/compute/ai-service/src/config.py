# -*- coding: utf-8 -*-
"""AI 服务配置"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 项目路径
SERVICE_ROOT = Path(__file__).resolve().parents[1]  # ai-service/
PROJECT_ROOT = SERVICE_ROOT.parents[2]  # tradecat/

# 加载环境变量
ENV_PATH = PROJECT_ROOT / "config" / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

# 添加项目根目录到 path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 数据库路径
_indicator_env = (os.getenv("INDICATOR_SQLITE_PATH") or "").strip()
if _indicator_env:
    _p = Path(_indicator_env)
    INDICATOR_DB = _p if _p.is_absolute() else (PROJECT_ROOT / _p)
else:
    INDICATOR_DB = PROJECT_ROOT / "assets" / "database" / "services" / "telegram-service" / "market_data.db"

# Bot Token（复用 telegram-service 配置）
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

# 代理
HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

# 提示词目录
PROMPTS_DIR = SERVICE_ROOT / "prompts"

# LLM 后端: cli (默认) 或 api
LLM_BACKEND = os.getenv("LLM_BACKEND", "cli")
