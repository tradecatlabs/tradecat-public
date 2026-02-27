# -*- coding: utf-8 -*-
"""LLM 客户端封装

支持两种调用方式：
1. API 网关（默认）- 通过 LLM客户端 调用
2. Gemini CLI - 本地命令行调用
"""
from __future__ import annotations

import json
import os
import sys
from typing import Tuple, List, Dict

from src.config import PROJECT_ROOT, HTTP_PROXY

# 导入工具
sys.path.insert(0, str(PROJECT_ROOT)) if str(PROJECT_ROOT) not in sys.path else None

# LLM 后端选择：cli / api / openai_compat（默认 cli）
LLM_BACKEND = os.getenv("LLM_BACKEND", "cli")
DEFAULT_MAX_TOKENS = 32000


async def call_llm(
    messages: List[Dict[str, str]],
    model: str | None = None,
    backend: str = None,
) -> Tuple[str, str]:
    """
    调用 LLM

    Args:
        messages: OpenAI 兼容的消息列表
        model: 模型名称
        backend: 后端选择 (api/cli)，默认读取环境变量 LLM_BACKEND
        
    Returns:
        (content, raw_response): 回复内容和原始响应
    """
    backend = backend or LLM_BACKEND
    model = model or os.getenv("LLM_MODEL") or "gemini-3-flash-preview"

    if backend == "cli":
        return await _call_gemini_cli(messages, model)
    if backend == "api":
        return await _call_api(messages, model)
    if backend in {"openai_compat", "openai"}:
        return await _call_openai_compat(messages, model)
    return await _call_api(messages, model)


async def _call_api(messages: List[Dict[str, str]], model: str) -> Tuple[str, str]:
    """通过 API 网关调用"""
    try:
        from assets.common.utils.LLM客户端 import 创建LLM客户端

        if HTTP_PROXY:
            os.environ["HTTP_PROXY"] = HTTP_PROXY
            os.environ["HTTPS_PROXY"] = HTTP_PROXY

        client = 创建LLM客户端()
        resp = client.聊天(
            messages=messages,
            model=model,
            temperature=0.5,
            max_tokens=_get_max_tokens(),
            stream=False,
            req_timeout=600,
        )
        content = resp.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            content = json.dumps(resp, ensure_ascii=False)
        return content, json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return f"[API_ERROR] {e}", json.dumps({"error": str(e)}, ensure_ascii=False)


async def _call_openai_compat(messages: List[Dict[str, str]], model: str) -> Tuple[str, str]:
    """通过 OpenAI 兼容接口直连调用（只需 API Key）"""
    import asyncio
    import urllib.request
    import urllib.error

    base_url = os.getenv("LLM_API_BASE_URL")
    api_key = os.getenv("EXTERNAL_API_KEY")

    if not base_url:
        return "[OPENAI_COMPAT_ERROR] LLM_API_BASE_URL 未配置", json.dumps({"error": "missing_base_url"}, ensure_ascii=False)
    if not api_key:
        return "[OPENAI_COMPAT_ERROR] EXTERNAL_API_KEY 未配置", json.dumps({"error": "missing_api_key"}, ensure_ascii=False)
    if model == "gemini-3-flash-preview" and not os.getenv("LLM_MODEL"):
        return "[OPENAI_COMPAT_ERROR] 请设置 LLM_MODEL", json.dumps({"error": "missing_model"}, ensure_ascii=False)

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "stream": False,
        "max_tokens": _get_max_tokens(),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _request():
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.read().decode("utf-8")

    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _request)
        resp = json.loads(raw)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            content = raw
        return content, raw
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = str(e)
        return f"[OPENAI_COMPAT_ERROR] {e}", json.dumps({"error": body}, ensure_ascii=False)
    except Exception as e:
        return f"[OPENAI_COMPAT_ERROR] {e}", json.dumps({"error": str(e)}, ensure_ascii=False)


async def _call_gemini_cli(messages: List[Dict[str, str]], model: str) -> Tuple[str, str]:
    """通过 Gemini CLI 无头模式调用"""
    import asyncio

    try:
        from assets.common.utils.gemini_client import call_gemini_with_system

        # 提取 system 和 user 消息
        system_prompt = None
        user_content = ""

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role == "user":
                user_content += content + "\n"

        user_content = user_content.strip()

        # 调用 Gemini CLI（同步转异步）
        loop = asyncio.get_event_loop()
        success, result = await loop.run_in_executor(
            None,
            lambda: call_gemini_with_system(
                system_prompt=system_prompt,
                user_content=user_content,
                model=model,
                timeout=300,
                use_proxy=True,  # 使用代理
            )
        )

        if success:
            return result, json.dumps({"source": "gemini_cli", "model": model}, ensure_ascii=False)
        else:
            return f"[CLI_ERROR] {result}", json.dumps({"error": result}, ensure_ascii=False)

    except ImportError as e:
        return f"[CLI_ERROR] gemini_client 未安装: {e}", json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        return f"[CLI_ERROR] {e}", json.dumps({"error": str(e)}, ensure_ascii=False)


def _get_max_tokens() -> int:
    raw = os.getenv("LLM_MAX_TOKENS")
    if not raw:
        return DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_MAX_TOKENS
    except ValueError:
        return DEFAULT_MAX_TOKENS


# 便捷函数
async def call_gemini(prompt: str, model: str = "gemini-3-flash-preview") -> str:
    """简单调用 Gemini（使用 CLI）"""
    messages = [{"role": "user", "content": prompt}]
    content, _ = await _call_gemini_cli(messages, model)
    return content


__all__ = ["call_llm", "call_gemini"]
