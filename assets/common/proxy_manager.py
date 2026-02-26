"""代理管理器 - 带重试和冷却逻辑"""

import os
import time
import logging
import requests
from typing import Optional

LOGGER = logging.getLogger(__name__)

# 冷却配置
PROXY_COOLDOWN_SECONDS = 3600  # 代理失败后冷却1小时
PROXY_RETRY_COUNT = 3          # 重试次数
PROXY_RETRY_DELAY = 2          # 重试间隔（秒）

# 状态
_proxy_disabled_until: float = 0
_original_proxy: Optional[str] = None


def _resolve_ping_url() -> Optional[str]:
    explicit = os.environ.get("BINANCE_PING_URL")
    if explicit:
        return explicit
    rest_base = (os.environ.get("BINANCE_REST_BASE_MAINNET") or os.environ.get("BINANCE_FAPI_BASE") or "").rstrip("/")
    if rest_base:
        return f"{rest_base}/fapi/v1/ping"
    return None


def get_proxy() -> Optional[str]:
    """获取代理，如果在冷却期则返回 None"""
    global _proxy_disabled_until, _original_proxy
    
    # 首次调用保存原始代理
    if _original_proxy is None:
        _original_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    
    # 检查冷却期
    if time.time() < _proxy_disabled_until:
        remaining = int(_proxy_disabled_until - time.time())
        LOGGER.debug(f"代理冷却中，剩余 {remaining}s")
        return None
    
    return _original_proxy


def disable_proxy(duration: int = PROXY_COOLDOWN_SECONDS):
    """禁用代理一段时间"""
    global _proxy_disabled_until
    _proxy_disabled_until = time.time() + duration
    LOGGER.warning(f"代理已禁用 {duration}s（{duration//3600}小时）")


def check_proxy() -> bool:
    """检查代理是否可用（带重试）"""
    proxy = get_proxy()
    if not proxy:
        return False
    ping_url = _resolve_ping_url()
    if not ping_url:
        LOGGER.warning("未配置 BINANCE_PING_URL/BINANCE_REST_BASE_MAINNET/BINANCE_FAPI_BASE，跳过代理健康检查")
        return True
    
    for i in range(PROXY_RETRY_COUNT):
        try:
            resp = requests.get(
                ping_url,
                proxies={"http": proxy, "https": proxy},
                timeout=3
            )
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        
        if i < PROXY_RETRY_COUNT - 1:
            time.sleep(PROXY_RETRY_DELAY)
    
    # 重试失败，进入冷却
    disable_proxy()
    return False


def request_with_proxy(url: str, **kwargs) -> requests.Response:
    """带代理管理的请求"""
    proxy = get_proxy()
    if proxy:
        kwargs.setdefault("proxies", {"http": proxy, "https": proxy})
    
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.ProxyError:
        # 代理错误，进入冷却
        disable_proxy()
        # 无代理重试一次
        kwargs.pop("proxies", None)
        return requests.get(url, **kwargs)
