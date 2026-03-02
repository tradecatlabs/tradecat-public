"""
服务配置加载模块。

对外提供 get_settings()，统一读取环境变量并做最小校验。
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    """通过环境变量配置 vis-service。"""

    service_name: str = Field("vis-service", description="服务名，用于健康检查显示")
    host: str = Field("0.0.0.0", description="服务监听地址")
    port: int = Field(8087, description="服务监听端口")
    token: Optional[str] = Field(None, description="访问令牌，用于简易鉴权")

    # Query Service（唯一读出口）：vis-service 禁止直连 DB
    query_service_base_url: str = Field(
        default="http://127.0.0.1:8088",
        description="Query Service 基地址（例如 http://127.0.0.1:8088）",
        env=["VIS_SERVICE_QUERY_SERVICE_BASE_URL", "QUERY_SERVICE_BASE_URL"],
    )
    query_service_token: Optional[str] = Field(
        default=None,
        description="可选：Query Service 内网 token（Header: X-Internal-Token）",
        env=["VIS_SERVICE_QUERY_SERVICE_TOKEN", "QUERY_SERVICE_TOKEN"],
    )
    query_timeout_seconds: float = Field(
        default=8.0,
        description="Query Service 请求超时（秒）",
        env=["VIS_SERVICE_QUERY_TIMEOUT_SECONDS", "QUERY_SERVICE_TIMEOUT_SECONDS"],
    )

    cache_ttl_seconds: int = Field(300, description="渲染结果缓存时间，秒")
    cache_max_items: int = Field(128, description="缓存条目上限")

    class Config:
        env_prefix = "VIS_SERVICE_"
        case_sensitive = False
        env_file = None  # 由启动脚本加载 assets/config/.env 后生效


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """缓存后的配置获取函数，避免重复解析环境变量。"""
    return Settings()
