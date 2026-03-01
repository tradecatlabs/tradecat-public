"""
事件系统测试
"""
from datetime import datetime


def test_signal_event_creation():
    """测试 SignalEvent 创建"""
    from src.events.types import SignalEvent
    
    event = SignalEvent(
        symbol="BTCUSDT",
        signal_type="price_surge",
        direction="BUY",
        strength=75,
        message_key="signal.pg.msg.price_surge",
        message_params={"pct": "3.5"},
    )
    
    assert event.symbol == "BTCUSDT"
    assert event.direction == "BUY"
    assert event.strength == 75
    assert event.source == "pg"  # 默认值


def test_signal_event_to_dict():
    """测试 SignalEvent 序列化"""
    from src.events.types import SignalEvent
    
    event = SignalEvent(
        symbol="ETHUSDT",
        signal_type="volume_spike",
        direction="ALERT",
        strength=60,
        message_key="signal.pg.msg.volume_spike",
        message_params={"ratio": "5.2"},
        price=3500.0,
    )
    
    data = event.to_dict()
    
    assert data["symbol"] == "ETHUSDT"
    assert data["price"] == 3500.0
    assert "timestamp" in data


def test_signal_event_from_dict():
    """测试 SignalEvent 反序列化"""
    from src.events.types import SignalEvent
    
    data = {
        "symbol": "SOLUSDT",
        "signal_type": "oi_surge",
        "direction": "ALERT",
        "strength": 80,
        "message_key": "signal.pg.msg.oi_surge",
        "message_params": {"pct": "5.0"},
        "timestamp": "2026-01-11T12:00:00",
    }
    
    event = SignalEvent.from_dict(data)
    
    assert event.symbol == "SOLUSDT"
    assert event.strength == 80
    assert isinstance(event.timestamp, datetime)


def test_signal_publisher_subscribe():
    """测试 SignalPublisher 订阅"""
    from src.events.publisher import SignalPublisher
    from src.events.types import SignalEvent
    
    # 清理
    SignalPublisher.clear()
    
    received = []
    
    def callback(event: SignalEvent):
        received.append(event)
    
    SignalPublisher.subscribe(callback)
    assert SignalPublisher.subscriber_count() == 1
    
    # 发布
    event = SignalEvent(
        symbol="BTCUSDT",
        signal_type="test",
        direction="BUY",
        strength=50,
        message_key="test.key",
    )
    SignalPublisher.publish(event)
    
    assert len(received) == 1
    assert received[0].symbol == "BTCUSDT"
    
    # 清理
    SignalPublisher.clear()


def test_signal_publisher_unsubscribe():
    """测试取消订阅"""
    from src.events.publisher import SignalPublisher
    from src.events.types import SignalEvent
    
    SignalPublisher.clear()
    
    received = []
    
    def callback(event: SignalEvent):
        received.append(event)
    
    SignalPublisher.subscribe(callback)
    SignalPublisher.unsubscribe(callback)
    
    assert SignalPublisher.subscriber_count() == 0
    
    SignalPublisher.clear()


def test_signal_publisher_clear_persist():
    """测试清理持久化回调"""
    from src.events.publisher import SignalPublisher
    from src.events.types import SignalEvent

    SignalPublisher.clear()

    received = []

    def persist_callback(event: SignalEvent):
        received.append(event)

    SignalPublisher.register_persist(persist_callback)
    SignalPublisher.clear()

    SignalPublisher.publish(
        SignalEvent(
            symbol="BTCUSDT",
            signal_type="test",
            direction="BUY",
            strength=50,
            message_key="test.key",
        )
    )

    assert received == []


def test_pg_cooldown_failure_no_mem_update(monkeypatch):
    """PG 冷却写盘失败不更新内存"""
    import src.engines.pg_engine as pg_engine

    class FailingStorage:
        def load_all(self):
            return {}

        def set(self, *args, **kwargs):
            raise RuntimeError("fail")

    monkeypatch.setattr(pg_engine, "get_cooldown_storage", lambda: FailingStorage())
    monkeypatch.setattr(pg_engine, "get_history", lambda: object())
    engine = pg_engine.PGSignalEngine(db_url="postgresql://invalid", symbols=["BTCUSDT"])

    key = "pg:BTCUSDT_test"
    assert engine._set_cooldown(key) is False
    assert key not in engine.cooldowns
