"""
信号历史记录测试（不依赖真实数据库）
"""

from datetime import datetime, timezone


def test_normalize_signal_event(sample_signal_event):
    """SignalEvent 能被规范化为可写入的结构"""
    from src.storage.history import PgSignalHistory

    data = PgSignalHistory._normalize_signal(sample_signal_event, source="pg")
    assert data["symbol"] == "BTCUSDT"
    assert data["direction"] == "BUY"
    assert data["timeframe"] == "5m"
    assert data["message"] == sample_signal_event.message_key
    assert data["source"] == "pg"
    assert "message_key" in data["extra"]
    assert data["extra"]["message_key"] == sample_signal_event.message_key
    assert data["extra"]["message_params"] == sample_signal_event.message_params


def test_parse_ts_accepts_z_suffix():
    from src.storage.history import PgSignalHistory

    dt = PgSignalHistory._parse_ts("2026-01-11T12:00:00Z")
    assert dt.tzinfo is not None
    assert dt.isoformat().startswith("2026-01-11T12:00:00")


def test_format_history_text():
    from src.storage.history import PgSignalHistory

    history = PgSignalHistory.__new__(PgSignalHistory)
    records = [
        {
            "timestamp": datetime(2026, 1, 11, 12, 0, tzinfo=timezone.utc).isoformat(),
            "symbol": "BTCUSDT",
            "signal_type": "price_surge",
            "direction": "BUY",
            "strength": 80,
        }
    ]
    text = history.format_history_text(records, title="测试历史")
    assert "测试历史" in text
    assert "BTC" in text
    assert "price_surge" in text

