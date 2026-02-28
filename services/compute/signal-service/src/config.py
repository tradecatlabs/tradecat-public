"""
Signal Service 配置
"""

import os
from pathlib import Path

# 路径
SRC_DIR = Path(__file__).parent
PROJECT_ROOT = SRC_DIR.parent
REPO_ROOT = PROJECT_ROOT.parents[2]


# 数据库配置
def get_database_url() -> str:
    """获取 TimescaleDB 连接 URL"""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # 优先 assets/config/.env；兼容旧路径 config/.env（只读回退）
    env_file = REPO_ROOT / "assets" / "config" / ".env"
    if not env_file.exists():
        env_file = REPO_ROOT / "config" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "DATABASE_URL":
                return v.strip().strip("\"'")
    return "postgresql://postgres:postgres@localhost:5433/market_data"


# 信号检测配置
DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]
DEFAULT_MIN_VOLUME = 100000
DEFAULT_CHECK_INTERVAL = 60  # 秒
COOLDOWN_SECONDS = 300  # 同一信号冷却时间
# 数据新鲜度阈值（秒），超过则视为陈旧数据不参与信号计算
DATA_MAX_AGE_SECONDS = int(os.environ.get("SIGNAL_DATA_MAX_AGE", "600"))

# 历史记录配置
MAX_RETENTION_DAYS = int(os.environ.get("SIGNAL_HISTORY_RETENTION_DAYS", "30"))
