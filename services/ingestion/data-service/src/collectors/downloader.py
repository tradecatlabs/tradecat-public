"""下载器"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

import requests

logger = logging.getLogger(__name__)


class RateLimiterProtocol(Protocol):
    """限流器协议"""

    def acquire(self, weight: int = 1) -> None: ...


class Downloader:
    """
    一个健壮的文件下载器，支持代理和自动重试。
    """

    def __init__(
        self,
        rate_limiter: RateLimiterProtocol,
        http_proxy: str | None = None,
        fallback_proxy: str | None = None,
    ):
        """
        初始化 Downloader。

        :param rate_limiter: 全局速率限制器实例。
        :param http_proxy: 主 HTTP/HTTPS 代理。
        :param fallback_proxy: 备用代理，在主代理失败后使用。
        """
        self._limiter = rate_limiter
        self._proxies = self._create_proxy_dict(http_proxy)
        self._fallback_proxies = self._create_proxy_dict(fallback_proxy)

    @staticmethod
    def _create_proxy_dict(proxy_url: str | None) -> dict[str, str] | None:
        """从 URL 创建 requests 库所需的代理字典。"""
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

    def download(self, url: str, destination: Path, weight: int = 1) -> bool:
        """
        下载单个文件，支持两级代理重试。

        会首先尝试直连（如果未设置主代理），然后是主代理，最后是备用代理。
        如果文件已存在，则跳过下载。

        :param url: 要下载的文件的 URL。
        :param destination: 文件保存路径。
        :param weight: 本次请求在速率限制器中的权重。
        :return: 如果下载成功或文件已存在，返回 True，否则返回 False。
        """
        if destination.exists():
            logger.debug("文件已存在，跳过下载: %s", destination)
            return True

        self._limiter.acquire(weight)

        # 定义尝试顺序：直连/主代理 -> 备用代理
        attempts = [self._proxies, self._fallback_proxies]

        for i, proxies in enumerate(attempts):
            if i > 0 and attempts[i - 1] == proxies:  # 如果代理配置相同，则不重复尝试
                continue

            proxy_name = "备用代理" if proxies == self._fallback_proxies else "主代理/直连"
            try:
                # 使用 stream=True 进行流式下载，更高效
                with requests.get(url, proxies=proxies, timeout=60, stream=True) as r:
                    if r.status_code == 404:
                        logger.warning("资源未找到 (404): %s", url)
                        return False  # 404 是确定性失败，无需重试

                    r.raise_for_status()  # 对其他错误状态码抛出异常

                    # 确保目标目录存在
                    destination.parent.mkdir(parents=True, exist_ok=True)

                    with open(destination, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)

                    logger.debug("下载成功 (%s): %s", proxy_name, url)
                    return True

            except requests.RequestException as e:
                logger.warning("下载失败 (%s) - %s: %s", proxy_name, url, e)

        logger.error("所有下载尝试均失败: %s", url)
        return False
