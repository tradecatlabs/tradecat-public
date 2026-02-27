"""路径工具"""
from pathlib import Path

# telegram-service 根目录
SERVICE_ROOT = Path(__file__).parent.parent.parent  # utils -> src -> telegram-service
PROJECT_ROOT = SERVICE_ROOT.parents[2]              # services -> tradecat

# 数据库目录
DATABASE_DIR = PROJECT_ROOT / "assets" / "database" / "services" / "telegram-service"


def 获取数据库目录() -> Path:
    """返回 telegram-service 数据库目录"""
    return DATABASE_DIR


__all__ = ["获取数据库目录", "SERVICE_ROOT", "PROJECT_ROOT", "DATABASE_DIR"]
