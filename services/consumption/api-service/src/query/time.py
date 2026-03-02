from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


UTC = timezone.utc
SHANGHAI = timezone(timedelta(hours=8))


def normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_ts_any(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return normalize_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # 统一 ISO：Z -> +00:00；空格 -> T
    s = s.replace(" ", "T").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    return normalize_utc(dt if dt.tzinfo else dt.replace(tzinfo=UTC))


@dataclass(frozen=True)
class TsBundle:
    ts_utc: str
    ts_ms: int
    ts_shanghai: str


def format_ts_bundle(dt: datetime) -> TsBundle:
    dt_utc = normalize_utc(dt) or datetime.now(tz=UTC)
    dt_utc = dt_utc.replace(microsecond=0)
    ts_utc = dt_utc.isoformat().replace("+00:00", "Z")
    ts_ms = int(dt_utc.timestamp() * 1000)
    ts_sh = dt_utc.astimezone(SHANGHAI).isoformat()
    return TsBundle(ts_utc=ts_utc, ts_ms=ts_ms, ts_shanghai=ts_sh)

