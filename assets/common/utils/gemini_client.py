#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini CLI 本地调用封装

使用 Gemini CLI 无头模式调用 gemini-3-flash-preview 模型。
- 通过 stdin 传入用户内容
- 通过位置参数传入系统提示词
- 禁用工具调用，只返回纯文本

依赖：
- gemini CLI (npm install -g @google/gemini-cli)
- 需要 OAuth 登录或配置 GEMINI_API_KEY 环境变量

用法：
    from gemini_client import call_gemini, call_gemini_with_system
    
    # 简单调用
    result = call_gemini("你好，请介绍一下自己")
    
    # 带系统提示词
    result = call_gemini_with_system(
        system_prompt="你是一个专业的翻译助手",
        user_content="Hello, world!"
    )
"""
from __future__ import annotations

import os
import subprocess
import logging
from typing import Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# 默认模型（按指南推荐使用最新版本）
DEFAULT_MODEL = "gemini-3-flash-preview"

# Gemini CLI 路径（自动检测）
GEMINI_CLI = os.getenv("GEMINI_CLI_PATH") or "gemini"


def _get_proxy_env() -> dict:
    """获取代理环境变量"""
    env = os.environ.copy()
    proxy = (
        os.getenv("HTTP_PROXY") or 
        os.getenv("HTTPS_PROXY") or 
        os.getenv("http_proxy") or 
        os.getenv("https_proxy")
    )
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


def call_gemini(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
    use_proxy: bool = True,
) -> Tuple[bool, str]:
    """
    调用 Gemini CLI（无系统提示词）
    
    Args:
        prompt: 用户提示词
        model: 模型名称，默认 gemini-3-flash-preview
        timeout: 超时时间（秒）
        use_proxy: 是否使用代理
        
    Returns:
        (success, result): 成功标志和结果文本
    """
    return call_gemini_with_system(
        system_prompt=None,
        user_content=prompt,
        model=model,
        timeout=timeout,
        use_proxy=use_proxy,
    )


def call_gemini_with_system(
    system_prompt: Optional[str],
    user_content: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
    use_proxy: bool = True,
) -> Tuple[bool, str]:
    """
    调用 Gemini CLI（带系统提示词）- 无头模式
    
    按照 GEMINI-HEADLESS.md 标准：
    - 系统提示词作为位置参数传入
    - 用户内容通过 stdin 传入
    - --allowed-tools '' 禁用工具调用
    - --output-format text 纯文本输出
    
    Args:
        system_prompt: 系统提示词（作为位置参数）
        user_content: 用户内容（通过 stdin 传入）
        model: 模型名称
        timeout: 超时时间（秒）
        use_proxy: 是否使用代理
        
    Returns:
        (success, result): 成功标志和结果文本
    """
    # 构建命令
    cmd = [
        GEMINI_CLI,
        "-m", model,
        "--output-format", "text",
        "--allowed-tools", "",  # 禁用工具调用
    ]
    
    # 系统提示词作为位置参数
    if system_prompt:
        cmd.append(system_prompt)
    
    # 环境变量
    env = _get_proxy_env() if use_proxy else os.environ.copy()
    
    try:
        logger.debug(f"执行 Gemini CLI: {' '.join(cmd[:6])}...")
        
        result = subprocess.run(
            cmd,
            input=user_content,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"退出码: {result.returncode}"
            logger.error(f"Gemini CLI 失败: {error_msg}")
            return False, error_msg
        
        output = result.stdout.strip()
        logger.debug(f"Gemini 返回 {len(output)} 字符")
        return True, output
        
    except subprocess.TimeoutExpired:
        logger.error(f"Gemini CLI 超时 ({timeout}s)")
        return False, f"超时 ({timeout}s)"
    except FileNotFoundError:
        logger.error(f"Gemini CLI 未找到: {GEMINI_CLI}")
        return False, f"Gemini CLI 未找到，请安装: npm install -g @google/generative-ai-cli"
    except Exception as e:
        logger.error(f"Gemini CLI 异常: {e}")
        return False, str(e)


def call_gemini_file(
    file_path: str,
    system_prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
) -> Tuple[bool, str]:
    """
    读取文件内容并调用 Gemini
    
    Args:
        file_path: 文件路径
        system_prompt: 系统提示词
        model: 模型名称
        timeout: 超时时间
        
    Returns:
        (success, result)
    """
    path = Path(file_path)
    if not path.exists():
        return False, f"文件不存在: {file_path}"
    
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"读取文件失败: {e}"
    
    return call_gemini_with_system(
        system_prompt=system_prompt,
        user_content=content,
        model=model,
        timeout=timeout,
    )


async def call_gemini_async(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
) -> Tuple[bool, str]:
    """
    异步调用 Gemini CLI
    
    Args:
        prompt: 用户提示词
        model: 模型名称
        timeout: 超时时间
        
    Returns:
        (success, result)
    """
    import asyncio
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: call_gemini(prompt, model, timeout)
    )


async def call_gemini_with_system_async(
    system_prompt: Optional[str],
    user_content: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
) -> Tuple[bool, str]:
    """
    异步调用 Gemini CLI（带系统提示词）
    """
    import asyncio
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: call_gemini_with_system(system_prompt, user_content, model, timeout)
    )


# ============ 便捷函数 ============

def chat(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """
    简单聊天接口，失败时抛出异常
    
    Args:
        prompt: 用户提示词
        model: 模型名称
        
    Returns:
        模型回复文本
        
    Raises:
        RuntimeError: 调用失败时
    """
    success, result = call_gemini(prompt, model)
    if not success:
        raise RuntimeError(f"Gemini 调用失败: {result}")
    return result


def analyze(content: str, instruction: str, model: str = DEFAULT_MODEL) -> str:
    """
    分析内容接口
    
    Args:
        content: 待分析内容
        instruction: 分析指令（作为系统提示词）
        model: 模型名称
        
    Returns:
        分析结果
        
    Raises:
        RuntimeError: 调用失败时
    """
    success, result = call_gemini_with_system(instruction, content, model)
    if not success:
        raise RuntimeError(f"Gemini 调用失败: {result}")
    return result


# ============ 测试 ============

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.DEBUG)
    
    # 简单测试
    print("=" * 50)
    print("测试 Gemini CLI 调用")
    print("=" * 50)
    
    success, result = call_gemini("你好，请用一句话介绍自己")
    
    if success:
        print(f"\n✅ 成功:\n{result}")
    else:
        print(f"\n❌ 失败: {result}")
        sys.exit(1)
    
    # 带系统提示词测试
    print("\n" + "=" * 50)
    print("测试带系统提示词")
    print("=" * 50)
    
    success, result = call_gemini_with_system(
        system_prompt="你是一个专业的翻译助手，将用户输入翻译成英文，只输出翻译结果",
        user_content="今天天气真好",
    )
    
    if success:
        print(f"\n✅ 成功:\n{result}")
    else:
        print(f"\n❌ 失败: {result}")
        sys.exit(1)
