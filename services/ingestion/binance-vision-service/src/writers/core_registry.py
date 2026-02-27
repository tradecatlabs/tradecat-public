"""core.* 维表解析与注册（最小可用、可幂等）。

目标（说人话）：
- 事实表使用 (venue_id, instrument_id) 作为短主键，但采集侧天然拿到的是 (exchange, symbol)；
- 这里提供一个“最小且可重复执行”的映射层：
  - 确保 core.venue 存在对应 venue_code
  - 确保 core.instrument 存在对应 instrument
  - 确保 core.symbol_map 存在 (venue_id, symbol) -> instrument_id 的当前映射

约束与取舍：
- 不引入额外 schema/table；只使用既有 core.*（见 008_multi_market_core_and_storage.sql）
- 不试图一次性做完“金融工具规范化”（那会变复杂）；先保证写库可落地且可追溯。
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import psycopg

logger = logging.getLogger(__name__)

KNOWN_QUOTES = ("USDT", "USDC", "BUSD", "USD", "TUSD", "FDUSD")


def _split_base_quote(symbol: str) -> Tuple[Optional[str], Optional[str]]:
    """尽力从 Binance 原生 symbol 推断 base/quote。

说明：
- 对于 BTCUSDT / ETHUSDT 等可稳定解析。
- 对于交割合约/复杂符号（含 '_' 或特殊后缀）无法保证正确，返回 (None, None)。
"""

    sym = str(symbol).upper().strip()
    if not sym:
        return None, None

    # 交割合约常见形态：BTCUSDT_240329（先取 '_' 前）
    main = sym.split("_", 1)[0]
    for quote in KNOWN_QUOTES:
        if main.endswith(quote) and len(main) > len(quote):
            return main[: -len(quote)], quote
    return None, None


def _infer_instrument_type(symbol: str, *, product: str) -> str:
    """用最小规则推断 instrument_type（只用于 core.instrument 的描述字段）。"""

    sym = str(symbol).upper()
    if "_" in sym:
        return "future"
    if product in {"futures_um", "futures_cm"}:
        return "perp"
    return "unknown"


class CoreRegistry:
    """core 维表的最小注册器（带本地缓存）。"""

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn
        self._venue_id_cache: dict[str, int] = {}
        self._instrument_id_cache: dict[tuple[int, str], int] = {}

    def _qualify_venue_code(self, *, venue_code: str, product: str) -> str:
        """把 product 纳入 venue_code 的键空间，避免不同市场/产品的同名 symbol 发生碰撞。

        为什么要这样做（说人话）：
        - core.symbol_map 的主键空间是 (venue_id, symbol, effective_from)，并且我们要加一条硬约束：
          同一 (venue_id, symbol) 只能存在 1 条 active（effective_to IS NULL）。
        - 如果 venue_code 只有 'binance'，那 spot / futures_um / futures_cm / option 都会共享 'BTCUSDT' 这种同名 symbol，
          后续接入就必然撞车。
        - 最小且不改 schema 的做法：把“产品维度”折叠进 venue_code（例如 binance_futures_cm / binance_spot）。

        兼容性：
        - 若历史运行库曾把 futures_um 写在 venue_code=binance 下，需要先做一次性迁移：
          core.venue: binance -> binance_futures_um（保持 venue_id 不变）
        """

        base = str(venue_code).strip().lower()
        prod = str(product).strip().lower()
        if not prod:
            return base
        suffix = f"_{prod}"
        if base.endswith(suffix):
            return base
        return f"{base}{suffix}"

    def _lock_symbol_mapping(self, *, venue_code: str, symbol: str, cursor: psycopg.Cursor) -> None:
        """对 (venue_code, symbol) 的“映射创建”加事务级互斥锁，避免并发下重复造 instrument / 重复插 symbol_map。

        说明：
        - 事实表写入通常存在“实时 + 回填”两条链路并发启动的可能；
        - core.instrument 没有天然唯一键（除 PK），因此并发下必须显式加锁，才能保证“先查再建”语义稳定。
        """

        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (str(venue_code).strip().lower(), str(symbol).strip().upper()),
        )

    def get_or_create_venue_id(
        self,
        venue_code: str,
        *,
        venue_name: Optional[str] = None,
        timezone: str = "UTC",
        cursor: Optional[psycopg.Cursor] = None,
    ) -> int:
        code = str(venue_code).strip().lower()
        if not code:
            raise ValueError("venue_code 不能为空")
        if code in self._venue_id_cache:
            return int(self._venue_id_cache[code])

        sql = """
        INSERT INTO core.venue (venue_code, venue_name, timezone)
        VALUES (%s, %s, %s)
        ON CONFLICT (venue_code) DO UPDATE
        SET venue_name = EXCLUDED.venue_name,
            timezone  = EXCLUDED.timezone
        RETURNING venue_id
        """

        name = (venue_name or code).strip()
        cur = cursor or self._conn.cursor()
        try:
            cur.execute(sql, (code, name, str(timezone)))
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"创建/获取 venue_id 失败: {code}")
            venue_id = int(row[0])
        finally:
            if cursor is None:
                cur.close()

        self._venue_id_cache[code] = venue_id
        return venue_id

    def get_or_create_instrument_id(
        self,
        *,
        venue_id: int,
        venue_code: str,
        symbol: str,
        product: str,
        cursor: Optional[psycopg.Cursor] = None,
    ) -> int:
        if venue_id <= 0:
            raise ValueError("venue_id 必须 > 0")
        sym = str(symbol).upper().strip()
        if not sym:
            raise ValueError("symbol 不能为空")

        cache_key = (int(venue_id), sym)
        if cache_key in self._instrument_id_cache:
            return int(self._instrument_id_cache[cache_key])

        cur = cursor or self._conn.cursor()
        try:
            # 并发保护：避免两个链路同时“看不到映射 -> 都创建 instrument -> 都插入 symbol_map”
            self._lock_symbol_mapping(venue_code=venue_code, symbol=sym, cursor=cur)

            # 1) 先看当前映射（避免重复造 instrument）
            cur.execute(
                """
                SELECT instrument_id
                FROM core.symbol_map
                WHERE venue_id = %s AND symbol = %s AND effective_to IS NULL
                ORDER BY effective_from DESC
                LIMIT 1
                """,
                (int(venue_id), sym),
            )
            row = cur.fetchone()
            if row:
                instrument_id = int(row[0])
                self._instrument_id_cache[cache_key] = instrument_id
                return instrument_id

            # 2) 不存在则创建 instrument + symbol_map
            base, quote = _split_base_quote(sym)
            instrument_type = _infer_instrument_type(sym, product=product)

            cur.execute(
                """
                INSERT INTO core.instrument (asset_class, instrument_type, base_currency, quote_currency, meta)
                VALUES (
                  'crypto',
                  %s,
                  %s,
                  %s,
                  jsonb_build_object(
                    'source', 'binance_vision',
                    'venue_code', %s::TEXT,
                    'symbol', %s::TEXT,
                    'product', %s::TEXT
                  )
                )
                RETURNING instrument_id
                """,
                (instrument_type, base, quote, str(venue_code).lower(), sym, str(product)),
            )
            inst_row = cur.fetchone()
            if not inst_row:
                raise RuntimeError(f"创建 instrument 失败: venue={venue_code} symbol={sym}")
            instrument_id = int(inst_row[0])

            # 3) 创建/补齐 symbol_map
            # 重要：如果这是这个 (venue_id,symbol) 的“第一条映射”，把 effective_from 固定为 epoch。
            # 这样 readable view 若按 [effective_from,effective_to) 做 as-of 语义时，不会因“映射创建晚于历史回填”导致 symbol=NULL。
            cur.execute(
                """
                SELECT 1
                FROM core.symbol_map
                WHERE venue_id = %s AND symbol = %s
                LIMIT 1
                """,
                (int(venue_id), sym),
            )
            has_any_mapping = cur.fetchone() is not None
            effective_from = None if has_any_mapping else "1970-01-01 00:00:00+00"

            cur.execute(
                """
                INSERT INTO core.symbol_map (venue_id, symbol, instrument_id, effective_from, effective_to, meta)
                VALUES (
                  %s,
                  %s,
                  %s,
                  COALESCE(%s::timestamptz, NOW()),
                  NULL,
                  jsonb_build_object('source','auto','created_by','binance-vision-service')
                )
                """,
                (int(venue_id), sym, int(instrument_id), effective_from),
            )
        finally:
            if cursor is None:
                cur.close()

        self._instrument_id_cache[cache_key] = instrument_id
        logger.info("core.symbol_map 新增映射: venue=%s(%d) symbol=%s -> instrument_id=%d", venue_code, venue_id, sym, instrument_id)
        return instrument_id

    def resolve_venue_and_instrument_id(
        self,
        *,
        venue_code: str,
        symbol: str,
        product: str,
        cursor: Optional[psycopg.Cursor] = None,
    ) -> tuple[int, int]:
        base_code = str(venue_code).strip().lower()
        prod = str(product).strip().lower()
        qualified_venue_code = self._qualify_venue_code(venue_code=base_code, product=prod)

        cur = cursor or self._conn.cursor()
        try:
            # ==================== 兼容性门禁（P0） ====================
            # 目标：避免“旧运行库未迁移”时静默创建新 venue_id，导致事实表 split（同一产品写入不同 venue_id）。
            #
            # 当前已知高风险场景：
            # - 历史库：futures_um 曾使用 venue_code=binance
            # - 新代码：要求 futures_um 使用 venue_code=binance_futures_um（产品维度进入键空间）
            # 如果 operator 忘记先跑迁移脚本，get_or_create_venue_id() 会创建一条新 venue（新 venue_id），后果很难回收。
            if base_code == "binance" and prod == "futures_um" and qualified_venue_code != base_code:
                cur.execute("SELECT 1 FROM core.venue WHERE venue_code = %s LIMIT 1", (base_code,))
                base_exists = cur.fetchone() is not None
                cur.execute("SELECT 1 FROM core.venue WHERE venue_code = %s LIMIT 1", (qualified_venue_code,))
                qualified_exists = cur.fetchone() is not None
                if base_exists and not qualified_exists:
                    raise RuntimeError(
                        "检测到旧运行库 core.venue(venue_code='binance') 仍存在，但采集已要求 futures_um 使用 "
                        f"'{qualified_venue_code}'。为避免生成新的 venue_id 导致事实表 split，请先执行迁移脚本："
                        "assets/database/db/schema/018_core_binance_venue_code_futures_um.sql"
                    )

            vid = self.get_or_create_venue_id(qualified_venue_code, cursor=cur)
            iid = self.get_or_create_instrument_id(
                venue_id=vid,
                venue_code=qualified_venue_code,
                symbol=symbol,
                product=prod,
                cursor=cur,
            )
            return vid, iid
        finally:
            if cursor is None:
                cur.close()


__all__ = ["CoreRegistry"]
