# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_run_analysis_uses_default_prompt(monkeypatch):
    """未显式传 prompt_name 时，应使用默认提示词。"""
    from src import pipeline

    captured = {}

    def fake_fetch_payload(symbol: str, interval: str):
        return {"symbol": symbol, "interval": interval}

    def fake_build_prompt(prompt_name: str, payload, lang=None):
        captured["prompt_name"] = prompt_name
        return "SYSTEM", "{}"

    async def fake_call_llm(messages):
        return "ok", "{}"

    class DummyRecorder:
        def save_run(self, *args, **kwargs):
            return ""

    monkeypatch.setenv("AI_DEFAULT_PROMPT", "测试提示词")
    monkeypatch.setattr(pipeline, "fetch_payload", fake_fetch_payload)
    monkeypatch.setattr(pipeline, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(pipeline, "call_llm", fake_call_llm)
    monkeypatch.setattr(pipeline, "RunRecorder", lambda: DummyRecorder())

    result = await pipeline.run_analysis("BTCUSDT", "4h", None)

    assert captured["prompt_name"] == "测试提示词"
    assert result["analysis"] == "ok"


@pytest.mark.asyncio
async def test_large_payload_guard_returns_error(monkeypatch):
    """当 payload 超阈值且不允许强制 Gemini 时，应返回错误。"""
    from src import pipeline

    async def fake_call_llm(messages, backend=None):
        return "should_not_call", "{}"

    def fake_fetch_payload(symbol: str, interval: str):
        return {"symbol": symbol, "interval": interval}

    def fake_build_prompt(prompt_name: str, payload, lang=None):
        return "SYSTEM", "X" * 300_001

    class DummyRecorder:
        def save_run(self, *args, **kwargs):
            return ""

    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("AI_LARGE_PAYLOAD_CHAR_LIMIT", "200000")
    monkeypatch.setenv("AI_FORCE_GEMINI_ON_LARGE_PAYLOAD", "0")

    monkeypatch.setattr(pipeline, "fetch_payload", fake_fetch_payload)
    monkeypatch.setattr(pipeline, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(pipeline, "call_llm", fake_call_llm)
    monkeypatch.setattr(pipeline, "RunRecorder", lambda: DummyRecorder())

    result = await pipeline.run_analysis("BTCUSDT", "4h", "市场全局解析")
    assert result["status"] == "error"
    assert "PAYLOAD_TOO_LARGE" in result["analysis"]
