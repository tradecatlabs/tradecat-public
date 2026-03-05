from __future__ import annotations

import sys
from pathlib import Path


def _import_ccxt_adapter():
    # data-service 运行时依赖 `PYTHONPATH=src`（见 scripts/start.sh）。
    # tests 侧也用同样的 import 语义，避免“测试能跑、运行炸”的多世界分裂。
    src_dir = Path(__file__).resolve().parents[1] / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    import adapters.ccxt as ccxt_adapter  # noqa: E402

    return ccxt_adapter


def test_maybe_set_ban_from_error_sets_ban_with_source(monkeypatch):
    ccxt_adapter = _import_ccxt_adapter()

    calls: dict[str, object] = {}

    def fake_parse_ban(msg: str) -> float:
        calls["parse_ban_msg"] = msg
        return 2000.0

    def fake_set_ban(until: float, source: str | None = None):
        calls["set_ban"] = (until, source)

    monkeypatch.setattr(ccxt_adapter, "parse_ban", fake_parse_ban)
    monkeypatch.setattr(ccxt_adapter, "set_ban", fake_set_ban)
    monkeypatch.setattr(ccxt_adapter.time, "time", lambda: 1000.0)

    ok = ccxt_adapter._maybe_set_ban_from_error(
        "418 I'm a teapot ... IP banned until 1772473135505",
        source="rest_gapfill",
    )
    assert ok is True
    assert isinstance(calls.get("parse_ban_msg"), str)
    assert calls.get("set_ban") == (2000.0, "rest_gapfill")


def test_maybe_set_ban_from_error_sets_short_ban_for_429(monkeypatch):
    ccxt_adapter = _import_ccxt_adapter()

    calls: dict[str, object] = {}

    def fake_set_ban(until: float, source: str | None = None):
        calls["set_ban"] = (until, source)

    monkeypatch.setattr(ccxt_adapter, "set_ban", fake_set_ban)
    monkeypatch.setattr(ccxt_adapter.time, "time", lambda: 1000.0)

    ok = ccxt_adapter._maybe_set_ban_from_error("429 Too many requests", source="metrics")
    assert ok is True
    assert calls.get("set_ban") == (1060.0, "metrics")


def test_fetch_ohlcv_native_klines_exception_triggers_ban_and_short_circuits(monkeypatch):
    ccxt_adapter = _import_ccxt_adapter()

    # 避免测试触发真实限流/文件锁等待
    monkeypatch.setattr(ccxt_adapter, "acquire", lambda *_: None)
    monkeypatch.setattr(ccxt_adapter, "release", lambda *_: None)

    calls: dict[str, object] = {}

    def fake_set_ban(until: float, source: str | None = None):
        calls["set_ban"] = (until, source)

    monkeypatch.setattr(ccxt_adapter, "set_ban", fake_set_ban)
    monkeypatch.setattr(ccxt_adapter, "parse_ban", lambda *_: 2000.0)
    monkeypatch.setattr(ccxt_adapter.time, "time", lambda: 1000.0)

    class _FakeClient:
        def fapiPublicGetKlines(self, *_args, **_kwargs):
            raise RuntimeError("418 I'm a teapot ... IP banned until 1772473135505")

    monkeypatch.setattr(ccxt_adapter, "get_client", lambda *_: _FakeClient())

    out = ccxt_adapter.fetch_ohlcv(
        "binance",
        "BTCUSDT",
        interval="1m",
        since_ms=None,
        limit=1,
        ban_source="rest_gapfill",
    )
    assert out == []
    assert calls.get("set_ban") == (2000.0, "rest_gapfill")

