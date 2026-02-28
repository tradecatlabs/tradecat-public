#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排行榜数据访问层

数据源：
- SQLite: market_data.db（每个指标一张表）
- PG: DATABASE_URL 指向的库内 tg_cards schema（表结构严格对齐 SQLite）
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set


LOGGER = logging.getLogger(__name__)


# ============ 币种过滤（使用共享模块）============
import sys as _sys
from pathlib import Path as _Path
_repo_root = str(_Path(__file__).resolve().parents[5])
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)
from assets.common.symbols import get_configured_symbols_set


# 缓存配置的币种（延迟初始化）
_ALLOWED_SYMBOLS: Optional[Set[str]] = None
_SYMBOLS_LOADED = False
_latest_data_time: datetime | None = None   # 历史全局最大
_last_fetch_data_time: datetime | None = None  # 最近一次读取到的数据时间（本次 fetch）

def _get_allowed_symbols() -> Optional[Set[str]]:
    """获取允许的币种集合（延迟加载，首次调用时读取环境变量）"""
    global _ALLOWED_SYMBOLS, _SYMBOLS_LOADED
    if not _SYMBOLS_LOADED:
        _ALLOWED_SYMBOLS = get_configured_symbols_set()
        _SYMBOLS_LOADED = True
        if _ALLOWED_SYMBOLS:
            LOGGER.info("币种过滤已启用: %d 个币种", len(_ALLOWED_SYMBOLS))
    return _ALLOWED_SYMBOLS


def reset_symbols_cache():
    """
    重置币种缓存，下次调用 _get_allowed_symbols() 时会重新加载。
    用于热更新：修改 SYMBOLS_GROUPS 等配置后调用此函数。
    """
    global _ALLOWED_SYMBOLS, _SYMBOLS_LOADED
    _ALLOWED_SYMBOLS = None
    _SYMBOLS_LOADED = False
    LOGGER.info("币种缓存已重置，下次请求将重新加载")

_latest_data_time: datetime | None = None


def _update_latest(ts: datetime) -> None:
    """记录最近一次读取到的数据时间（模块级共享）。"""
    global _latest_data_time, _last_fetch_data_time
    if ts and ts != datetime.min:
        _last_fetch_data_time = ts
        if _latest_data_time is None or ts > _latest_data_time:
            _latest_data_time = ts


def get_latest_data_time() -> Optional[datetime]:
    """供 UI 查询最近一次 fetch 得到的数据时间；如未读取过数据返回 None。"""
    return _last_fetch_data_time or _latest_data_time


def _parse_timestamp(ts_str: str) -> datetime:
    """解析时间戳字符串为 datetime，支持多种格式（统一为无时区）"""
    if not ts_str:
        return datetime.min
    ts_str = ts_str.strip()
    # 处理 Z 后缀
    if ts_str.endswith('Z'):
        ts_str = ts_str[:-1]
    # 移除时区信息（统一为 naive datetime）
    if '+' in ts_str:
        ts_str = ts_str.split('+')[0]
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        LOGGER.warning("无法解析时间戳: %s", ts_str)
        return datetime.min


# 表名映射（简称 -> 实际表名）
TABLE_NAME_MAP = {
    # 基础
    "基础数据": "基础数据同步器.py",
    # 指标
    "ATR波幅榜单": "ATR波幅扫描器.py",
    "BB榜单": "布林带扫描器.py",
    "布林带榜单": "布林带扫描器.py",
    "CVD榜单": "CVD信号排行榜.py",
    "KDJ随机指标榜单": "KDJ随机指标扫描器.py",
    "K线形态榜单": "K线形态扫描器.py",
    "MACD柱状榜单": "MACD柱状扫描器.py",
    "MFI资金流量榜单": "MFI资金流量扫描器.py",
    "OBV能量潮榜单": "OBV能量潮扫描器.py",
    "VPVR榜单": "VPVR排行生成器.py",
    "VWAP榜单": "VWAP离线信号扫描.py",
    "主动买卖比榜单": "主动买卖比扫描器.py",
    "成交量比率榜单": "成交量比率扫描器.py",
    "支撑阻力榜单": "全量支撑阻力扫描器.py",
    "收敛发散榜单": "G，C点扫描器.py",
    "流动性榜单": "流动性扫描器.py",
    "谐波信号榜单": "谐波信号扫描器.py",
    "趋势线榜单": "趋势线榜单.py",
    "期货情绪聚合榜单": "期货情绪聚合表.py",
}


def format_symbol(sym: str) -> str:
    """将交易对显示为基础币种（去除 USDT 后缀），保持大写."""
    s = (sym or "").strip().upper()
    for suffix in ("USDT",):
        if s.endswith(suffix):
            return s[: -len(suffix)] or s
    return s


def _normalize_period_value(period: str) -> str:
    """统一周期表达 - 数据库内日线统一为 1d"""
    p = (period or "").strip().lower()
    if p in (f"{24}h", "1day"):
        return "1d"
    return p


def _period_to_db(period: str) -> str:
    """将业务周期转为数据库存储格式（统一日线为 1d）"""
    p = (period or "").strip().lower()
    if p in (f"{24}h", "1day"):
        return "1d"
    return p


# ============================================================
# SQLite 连接池（只读，线程安全）
# ============================================================
import threading
from queue import Queue, Empty

class _SQLitePool:
    """简单的 SQLite 只读连接池"""
    
    def __init__(self, db_path: Path, pool_size: int = 3):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: Queue = Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._initialized = False
    
    def _create_conn(self) -> Optional[sqlite3.Connection]:
        """创建新连接"""
        if not self.db_path.exists():
            LOGGER.error("market_data.db 不存在: %s", self.db_path)
            return None
        try:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                check_same_thread=False,
                timeout=10.0
            )
            conn.row_factory = sqlite3.Row
            for pragma in ("synchronous=OFF", "temp_store=MEMORY", "mmap_size=134217728"):
                try:
                    conn.execute(f"PRAGMA {pragma};")
                except Exception:
                    pass
            return conn
        except Exception as exc:
            LOGGER.error("创建 SQLite 连接失败: %s", exc)
            return None
    
    def get(self) -> Optional[sqlite3.Connection]:
        """获取连接（优先从池中取，否则新建）"""
        # 尝试从池中获取
        try:
            conn = self._pool.get_nowait()
            # 验证连接有效
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
                # 连接失效，创建新的
                try:
                    conn.close()
                except Exception:
                    pass
        except Empty:
            pass
        
        # 创建新连接
        return self._create_conn()
    
    def put(self, conn: Optional[sqlite3.Connection]) -> None:
        """归还连接到池中"""
        if conn is None:
            return
        try:
            # 池未满则放回，否则关闭
            self._pool.put_nowait(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    
    def close_all(self) -> None:
        """关闭所有连接"""
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break
            except Exception:
                pass


# 全局连接池实例（延迟初始化）
_global_pool: Optional[_SQLitePool] = None
_pool_lock = threading.Lock()

def _get_pool(db_path: Path) -> _SQLitePool:
    """获取或创建全局连接池"""
    global _global_pool
    with _pool_lock:
        if _global_pool is None or _global_pool.db_path != db_path:
            if _global_pool is not None:
                _global_pool.close_all()
            _global_pool = _SQLitePool(db_path, pool_size=3)
        return _global_pool


def _cleanup_pool():
    """进程退出时关闭连接池"""
    global _global_pool
    with _pool_lock:
        if _global_pool is not None:
            _global_pool.close_all()
            _global_pool = None


# 注册退出钩子
import atexit
atexit.register(_cleanup_pool)


# ============================================================
# RankingDataProvider（market_data.db）
# ============================================================
class RankingDataProvider:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        # __file__ = .../services/consumption/telegram-service/src/cards/data_provider.py
        # repo root = parents[5] (cards/src/telegram-service/consumption/services/<repo>)
        _project_root = Path(__file__).resolve().parents[5]
        _default_db = _project_root / "assets" / "database" / "services" / "telegram-service" / "market_data.db"

        # 支持相对路径：统一基于项目根目录解析为绝对路径
        def _resolve_path(p: Optional[Path]) -> Path:
            if p is None:
                return _default_db
            if not p.is_absolute():
                return (_project_root / p).resolve()
            return p

        # 支持通过环境变量覆盖（便于 sheets-service/运维拉取远程 DB 后复用同口径）
        # - MARKET_DATA_DB_PATH: 通用覆盖键
        # - TELEGRAM_MARKET_DATA_DB_PATH: telegram-service 专用覆盖键
        if db_path is None:
            env_p = (os.environ.get("MARKET_DATA_DB_PATH", "") or "").strip() or (
                os.environ.get("TELEGRAM_MARKET_DATA_DB_PATH", "") or ""
            ).strip()
            if env_p:
                try:
                    db_path = Path(env_p).expanduser()
                except Exception:
                    db_path = None

        self.db_path = _resolve_path(db_path)
        self._pool = _get_pool(self.db_path)

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        """从连接池获取连接"""
        return self._pool.get()
    
    def _return_conn(self, conn: Optional[sqlite3.Connection]) -> None:
        """归还连接到池"""
        self._pool.put(conn)

    def _resolve_table(self, name: str) -> str:
        """解析表名，支持简称和自动补 .py 后缀"""
        if name in TABLE_NAME_MAP:
            return TABLE_NAME_MAP[name]
        # 自动补 .py 后缀
        if not name.endswith('.py'):
            with_py = name + '.py'
            if with_py in TABLE_NAME_MAP:
                return TABLE_NAME_MAP[with_py]
            return with_py
        return name

    def _load_table(self, table: str) -> List[sqlite3.Row]:
        table = self._resolve_table(table)
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM '{table}'")
            return cur.fetchall()
        except Exception as exc:
            LOGGER.warning("读取表 %s 失败: %s", table, exc)
            return []
        finally:
            self._return_conn(conn)

    def _load_table_period(self, table: str, period: str) -> List[sqlite3.Row]:
        """按周期读取表"""
        table = self._resolve_table(table)
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info('{table}')")
            cols = [row[1] for row in cur.fetchall()]
            period_cols = [c for c in cols if c in ("周期", "period", "PERIOD")]
            if not period_cols:
                cur.execute(f"SELECT * FROM '{table}'")
                return cur.fetchall()

            target = _normalize_period_value(period)
            cand = list({target, target.upper(), period, period.lower(), period.upper()})
            placeholders = ",".join("?" for _ in cand)
            where = " OR ".join([f"{col} IN ({placeholders})" for col in period_cols])
            cur.execute(f"SELECT * FROM '{table}' WHERE {where}", cand * len(period_cols))
            return cur.fetchall()
        except Exception as exc:
            LOGGER.warning("读取表 %s 失败: %s", table, exc)
            return []
        finally:
            self._return_conn(conn)

    def _fetch_single_row(self, table: str, period: str, symbol: str) -> Dict:
        """按周期+交易对取一行"""
        table = self._resolve_table(table)
        conn = self._get_conn()
        if conn is None:
            return {}
        try:
            cur = conn.cursor()
            norm_p = _normalize_period_value(period)
            sym_full = symbol.upper()
            sym_with_usdt = sym_full if sym_full.endswith("USDT") else sym_full + "USDT"
            sym_base = sym_full.replace("USDT", "")
            
            cur.execute(f"PRAGMA table_info('{table}')")
            cols = [row[1] for row in cur.fetchall()]
            period_cols = [c for c in cols if c.lower() in ("周期", "period", "interval")]
            
            # 动态构建 symbol 查询条件（只用存在的列）
            sym_conds = []
            sym_params = []
            if "交易对" in cols:
                sym_conds.append("(upper(交易对)=? OR replace(upper(交易对),'USDT','')=?)")
                sym_params.extend([sym_with_usdt, sym_base])
            if "币种" in cols:
                sym_conds.append("upper(币种)=?")
                sym_params.append(sym_base)
            if "symbol" in cols:
                sym_conds.append("upper(symbol)=?")
                sym_params.append(sym_base)
            
            if not sym_conds:
                return {}
            sym_where = "(" + " OR ".join(sym_conds) + ")"
            
            # 动态构建 ORDER BY（只用存在的列）
            order_cols = []
            for oc in ["数据时间", "时间", "timestamp"]:
                if oc in cols:
                    order_cols.append(f"{oc} DESC")
            order_cols.append("rowid DESC")
            order_by = ", ".join(order_cols)

            if period_cols:
                period_vals = (norm_p, period.lower(), period.upper(), period)
                placeholders = ",".join("?" for _ in period_vals)
                period_cond = " OR ".join([f"{col} IN ({placeholders})" for col in period_cols])
                params = list(period_vals) * len(period_cols) + sym_params
                cur.execute(f"""
                    SELECT * FROM '{table}'
                    WHERE ({period_cond}) AND {sym_where}
                    ORDER BY {order_by}
                    LIMIT 1
                """, params)
            else:
                cur.execute(f"""
                    SELECT * FROM '{table}'
                    WHERE {sym_where}
                    ORDER BY {order_by}
                    LIMIT 1
                """, sym_params)
            row = cur.fetchone()
            return dict(row) if row else {}
        except Exception as exc:
            LOGGER.warning("读取表 %s 失败: %s", table, exc)
            return {}
        finally:
            self._return_conn(conn)

    # ---------------- 公共读取 ----------------
    def fetch_base(self, period: str) -> Dict[str, Dict]:
        """按周期取基础数据 - 只取最新批次（同一时间戳），按配置过滤币种"""
        rows = self._load_table_period("基础数据", period)
        target_period = _normalize_period_value(period)
        allowed = _get_allowed_symbols()
        
        # 第一遍：找出最新时间戳
        max_ts = datetime.min
        for row in rows:
            r = dict(row)
            r_period = _normalize_period_value(str(r.get("周期", "")))
            if r_period != target_period:
                continue
            sym = str(r.get("交易对", "")).upper()
            if allowed and sym not in allowed:
                continue
            ts = _parse_timestamp(str(r.get("数据时间", "")))
            if ts > max_ts:
                max_ts = ts

        _update_latest(max_ts)
        
        if max_ts == datetime.min:
            return {}
        
        # 第二遍：只取最新时间戳的数据
        latest: Dict[str, Dict] = {}
        for row in rows:
            r = dict(row)
            r_period = _normalize_period_value(str(r.get("周期", "")))
            if r_period != target_period:
                continue
            ts = _parse_timestamp(str(r.get("数据时间", "")))
            sym = str(r.get("交易对", "")).upper()
            if allowed and sym not in allowed:
                continue
            if ts == max_ts and sym and sym not in latest:
                latest[sym] = r
        return latest

    def fetch_base_with_field(self, period: str, field: str) -> Dict[str, Dict]:
        """按周期取基础数据 - 只取指定字段不为空的最新批次"""
        rows = self._load_table_period("基础数据", period)
        target_period = _normalize_period_value(period)
        allowed = _get_allowed_symbols()
        field = (field or "").strip()
        if not field:
            return self.fetch_base(period)

        max_ts = datetime.min
        for row in rows:
            r = dict(row)
            r_period = _normalize_period_value(str(r.get("周期", "")))
            if r_period != target_period:
                continue
            sym = str(r.get("交易对", "")).upper()
            if allowed and sym not in allowed:
                continue
            val = r.get(field)
            if val is None or val == "":
                continue
            ts = _parse_timestamp(str(r.get("数据时间", "")))
            if ts > max_ts:
                max_ts = ts

        _update_latest(max_ts)
        if max_ts == datetime.min:
            return {}

        latest: Dict[str, Dict] = {}
        for row in rows:
            r = dict(row)
            r_period = _normalize_period_value(str(r.get("周期", "")))
            if r_period != target_period:
                continue
            sym = str(r.get("交易对", "")).upper()
            if allowed and sym not in allowed:
                continue
            val = r.get(field)
            if val is None or val == "":
                continue
            ts = _parse_timestamp(str(r.get("数据时间", "")))
            if ts == max_ts and sym and sym not in latest:
                latest[sym] = r
        return latest

    def fetch_metric(self, table: str, period: str) -> List[Dict]:
        """通用指标读取：按周期过滤，每个币种取自身最新一条（不强制同一时间戳），按配置过滤币种"""
        rows = self._load_table_period(table, period)
        target_period = _normalize_period_value(period)
        allowed = _get_allowed_symbols()

        latest_per_symbol: Dict[str, Dict] = {}
        latest_ts: datetime = datetime.min

        for row in rows:
            r = dict(row)
            r_period = _normalize_period_value(str(r.get("周期", "")))
            if r_period != target_period:
                continue
            sym = str(r.get("交易对", "")).upper()
            if not sym:
                continue
            if allowed and sym not in allowed:
                continue
            ts = _parse_timestamp(str(r.get("数据时间", "")))
            if ts > latest_ts:
                latest_ts = ts
            prev = latest_per_symbol.get(sym)
            prev_ts = _parse_timestamp(str(prev.get("数据时间"))) if prev else datetime.min
            if ts >= prev_ts:
                latest_per_symbol[sym] = r

        if latest_ts != datetime.min:
            _update_latest(latest_ts)

        return list(latest_per_symbol.values())

    def fetch_base_row(self, period: str, symbol: str) -> Dict:
        return self._fetch_single_row("基础数据", period, symbol)

    def fetch_row(self, table: str, period: str, symbol: str, *,
                  symbol_keys: tuple = ("交易对", "币种", "symbol"),
                  base_fields: Optional[List[str]] = None) -> Dict:
        row = self._fetch_single_row(table, period, symbol)
        if not row:
            return {}
        base = self.fetch_base_row(period, symbol) or {}
        sym = symbol.upper()
        merged = dict(row)
        merged["symbol"] = sym
        merged["price"] = float(base.get("当前价格", row.get("当前价格", 0)) or 0)
        merged["quote_volume"] = float(base.get("成交额", row.get("成交额", 0)) or 0)
        merged["change_percent"] = float(base.get("变化率", 0) or 0)
        merged["updated_at"] = base.get("数据时间") or row.get("数据时间")
        for k in ["振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比"]:
            if k in base:
                merged[k] = base.get(k)
        if base_fields:
            for bf in base_fields:
                if bf in base:
                    merged[bf] = base.get(bf)
        return merged

    def merge_with_base(self, table: str, period: str,
                        symbol_keys: tuple = ("交易对", "币种", "symbol"),
                        base_fields: Optional[List[str]] = None) -> List[Dict]:
        """合并指标表与基础数据"""
        metrics = self.fetch_metric(table, period)
        if not metrics:
            return []
        base_map = self.fetch_base(period)
        merged: List[Dict] = []
        for r in metrics:
            sym = ""
            for key in symbol_keys:
                val = r.get(key)
                if val:
                    sym = str(val).upper()
                    break
            if not sym:
                continue
            base = base_map.get(sym, {})
            row = dict(r)
            row["symbol"] = sym
            row["price"] = float(base.get("当前价格", r.get("当前价格", 0)) or 0)
            row["quote_volume"] = float(base.get("成交额", r.get("成交额", 0)) or 0)
            row["change_percent"] = float(base.get("变化率", 0) or 0)
            row["updated_at"] = base.get("数据时间") or r.get("数据时间")
            for k in ["振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比"]:
                if k in base:
                    row[k] = base.get(k)
            if base_fields:
                for bf in base_fields:
                    if bf in base:
                        row[bf] = base.get(bf)
            merged.append(row)
        return merged

    def get_volume_rows(self, period: str) -> List[Dict]:
        metric_rows = self.fetch_metric("Volume", period)
        if not metric_rows:
            return []
        base_map = self.fetch_base(period)
        merged: List[Dict] = []
        for r in metric_rows:
            sym = str(r.get("交易对", "")).upper()
            if not sym:
                continue
            base = base_map.get(sym, {})
            merged.append({
                "symbol": sym,
                "quote_volume": float(base.get("成交额", 0) or 0),
                "base_volume": float(r.get("成交量", 0) or base.get("成交量", 0) or 0),
                "last_close": float(base.get("当前价格", 0) or 0),
                "first_close": float(base.get("开盘价", 0) or 0),
                "change_percent": float(base.get("变化率", 0) or 0) * 100 if abs(float(base.get("变化率", 0) or 0)) < 1 else float(base.get("变化率", 0) or 0),
                "ma5_volume": float(r.get("MA5成交量", 0) or 0),
                "ma20_volume": float(r.get("MA20成交量", 0) or 0),
                "updated_at": base.get("数据时间") or r.get("数据时间"),
            })
        return merged

    def get_atr_rows(self, period: str) -> List[Dict]:
        metrics = self.fetch_metric("ATR波幅榜单", period)
        if not metrics:
            return []
        base_map = self.fetch_base(period)
        out: List[Dict] = []
        for r in metrics:
            sym = str(r.get("交易对", r.get("币种", ""))).upper()
            if not sym:
                continue
            base = base_map.get(sym, {})
            out.append({
                "symbol": sym,
                "strength": float(r.get("强度", 0) or 0),
                "atr_pct": float(r.get("ATR百分比", 0) or 0),
                "price": float(base.get("当前价格", r.get("当前价格", 0)) or 0),
                "category": r.get("波动分类") or "-",
                "quote_volume": float(base.get("成交额", 0) or 0),
                "updated_at": (base.get("数据时间") or r.get("数据时间")),
            })
        return out


# ============================================================
# PgRankingDataProvider（PG: tg_cards schema）
# ============================================================


class _PgPool:
    """简单的 PG 连接池（只读）"""

    def __init__(self, dsn: str, pool_size: int = 3) -> None:
        self.dsn = (dsn or "").strip()
        self.pool_size = max(int(pool_size), 1)
        self._pool: Queue = Queue(maxsize=self.pool_size)
        self._lock = threading.Lock()
        self._initialized = False

    def _create_conn(self):
        try:
            import psycopg  # type: ignore
        except Exception as exc:
            LOGGER.error("psycopg 未安装，无法连接 PG: %s", exc)
            return None

        if not self.dsn:
            LOGGER.error("DATABASE_URL 未设置，无法连接 PG（请在 .env 中配置）")
            return None

        try:
            return psycopg.connect(self.dsn, connect_timeout=3, autocommit=True)
        except Exception as exc:
            LOGGER.error("创建 PG 连接失败: %s", exc)
            return None

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            for _ in range(self.pool_size):
                self._pool.put(self._create_conn())
            self._initialized = True

    def get(self):
        self._ensure_init()
        try:
            conn = self._pool.get_nowait()
        except Empty:
            return self._create_conn()

        if conn is None:
            return self._create_conn()

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return self._create_conn()

    def put(self, conn) -> None:
        if conn is None:
            return
        try:
            self._pool.put_nowait(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    def close_all(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
                if conn is not None:
                    conn.close()
            except Empty:
                break
            except Exception:
                pass


_global_pg_pool: Optional[_PgPool] = None
_pg_pool_lock = threading.Lock()


def _get_pg_pool(dsn: str) -> _PgPool:
    global _global_pg_pool
    with _pg_pool_lock:
        if _global_pg_pool is None or _global_pg_pool.dsn != (dsn or "").strip():
            if _global_pg_pool is not None:
                _global_pg_pool.close_all()
            _global_pg_pool = _PgPool(dsn, pool_size=3)
        return _global_pg_pool


def _cleanup_pg_pool() -> None:
    global _global_pg_pool
    with _pg_pool_lock:
        if _global_pg_pool is not None:
            _global_pg_pool.close_all()
            _global_pg_pool = None


atexit.register(_cleanup_pg_pool)


class PgRankingDataProvider:
    """
    PG 读取端：从 `tg_cards.*` 读取指标表（表结构严格对齐 SQLite）。

    设计目标：
    - 与 RankingDataProvider（SQLite）保持同一接口
    - 查询优先走 latest-per-symbol（DISTINCT ON），避免拉全历史
    """

    def __init__(self, *, dsn: str | None = None, schema: str | None = None) -> None:
        try:
            import psycopg  # noqa: F401  # type: ignore
        except Exception as exc:
            raise RuntimeError("psycopg 未安装，无法启用 PG 指标读取") from exc

        self.dsn = (dsn or os.environ.get("INDICATOR_PG_URL") or os.environ.get("DATABASE_URL") or "").strip()
        if not self.dsn:
            raise RuntimeError("DATABASE_URL 未设置，无法启用 PG 指标读取")
        self.schema = (schema or os.environ.get("INDICATOR_PG_SCHEMA") or "tg_cards").strip() or "tg_cards"
        self._pool = _get_pg_pool(self.dsn)
        self._cols_cache: Dict[str, List[str]] = {}

    def _get_conn(self):
        return self._pool.get()

    def _return_conn(self, conn) -> None:
        self._pool.put(conn)

    def _resolve_table(self, name: str) -> str:
        if name in TABLE_NAME_MAP:
            return TABLE_NAME_MAP[name]
        if not name.endswith(".py"):
            with_py = name + ".py"
            if with_py in TABLE_NAME_MAP:
                return TABLE_NAME_MAP[with_py]
            return with_py
        return name

    def _table_columns(self, table: str) -> List[str]:
        table = self._resolve_table(table)
        cached = self._cols_cache.get(table)
        if cached is not None:
            return cached

        conn = self._get_conn()
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema=%s AND table_name=%s
                    ORDER BY ordinal_position
                    """,
                    (self.schema, table),
                )
                cols = [str(r[0]) for r in (cur.fetchall() or [])]
                self._cols_cache[table] = cols
                return cols
        except Exception as exc:
            LOGGER.warning("读取 PG 表字段失败: %s.%s: %s", self.schema, table, exc)
            return []
        finally:
            self._return_conn(conn)

    def _period_candidates(self, period: str) -> List[str]:
        target = _normalize_period_value(period)
        return list({target, target.upper(), period, period.lower(), period.upper()})

    def _pick_ts_col(self, cols: List[str]) -> str | None:
        for c in ("数据时间", "时间", "timestamp"):
            if c in cols:
                return c
        return None

    def _pick_symbol_col(self, cols: List[str]) -> str | None:
        for c in ("交易对", "币种", "symbol"):
            if c in cols:
                return c
        return None

    def fetch_base(self, period: str) -> Dict[str, Dict]:
        table = self._resolve_table("基础数据")
        cols = self._table_columns(table)
        if not cols:
            return {}

        ts_col = self._pick_ts_col(cols) or "数据时间"
        sym_col = "交易对" if "交易对" in cols else (self._pick_symbol_col(cols) or "交易对")
        period_cols = [c for c in cols if str(c).lower() in ("周期", "period", "interval")]
        period_vals = self._period_candidates(period)
        allowed = _get_allowed_symbols()
        allowed_vals = sorted({s.upper() for s in (allowed or set())}) if allowed else []

        conn = self._get_conn()
        if conn is None:
            return {}
        try:
            from psycopg import sql  # type: ignore
            from psycopg.rows import dict_row  # type: ignore

            clauses: list[sql.Composed] = []
            params: list[object] = []

            if period_cols:
                sub = []
                for c in period_cols:
                    sub.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(c)))
                    params.append(period_vals)
                clauses.append(sql.SQL("(") + sql.SQL(" OR ").join(sub) + sql.SQL(")"))

            if allowed_vals and sym_col in cols:
                clauses.append(sql.SQL("upper({}) = ANY(%s)").format(sql.Identifier(sym_col)))
                params.append(allowed_vals)

            where_sql = sql.SQL("")
            has_filters = bool(clauses)
            if has_filters:
                where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)

            tbl = sql.Identifier(self.schema, table)

            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT MAX({}) AS max_ts FROM {}{}").format(sql.Identifier(ts_col), tbl, where_sql), params)
                row = cur.fetchone()
                max_ts = row[0] if row else None

            if not max_ts:
                _update_latest(datetime.min)
                return {}

            params2 = list(params) + [str(max_ts)]
            if has_filters:
                where2 = where_sql + sql.SQL(" AND {} = %s").format(sql.Identifier(ts_col))
            else:
                where2 = sql.SQL(" WHERE {} = %s").format(sql.Identifier(ts_col))

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("SELECT * FROM {}{}").format(tbl, where2), params2)
                rows = cur.fetchall() or []

            max_dt = _parse_timestamp(str(max_ts))
            _update_latest(max_dt)

            latest: Dict[str, Dict] = {}
            for r in rows:
                sym = str(r.get(sym_col, "") or "").upper()
                if not sym:
                    continue
                if allowed and sym not in allowed:
                    continue
                if sym not in latest:
                    latest[sym] = dict(r)
            return latest
        except Exception as exc:
            LOGGER.warning("PG 读取基础数据失败: %s", exc)
            return {}
        finally:
            self._return_conn(conn)

    def fetch_base_with_field(self, period: str, field: str) -> Dict[str, Dict]:
        field = (field or "").strip()
        if not field:
            return self.fetch_base(period)
        table = self._resolve_table("基础数据")
        cols = self._table_columns(table)
        if field not in cols:
            return self.fetch_base(period)

        ts_col = self._pick_ts_col(cols) or "数据时间"
        sym_col = "交易对" if "交易对" in cols else (self._pick_symbol_col(cols) or "交易对")
        period_cols = [c for c in cols if str(c).lower() in ("周期", "period", "interval")]
        period_vals = self._period_candidates(period)
        allowed = _get_allowed_symbols()
        allowed_vals = sorted({s.upper() for s in (allowed or set())}) if allowed else []

        conn = self._get_conn()
        if conn is None:
            return {}
        try:
            from psycopg import sql  # type: ignore
            from psycopg.rows import dict_row  # type: ignore

            clauses: list[sql.Composed] = []
            params: list[object] = []

            if period_cols:
                sub = []
                for c in period_cols:
                    sub.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(c)))
                    params.append(period_vals)
                clauses.append(sql.SQL("(") + sql.SQL(" OR ").join(sub) + sql.SQL(")"))

            clauses.append(sql.SQL("{} IS NOT NULL AND {} != ''").format(sql.Identifier(field), sql.Identifier(field)))

            if allowed_vals and sym_col in cols:
                clauses.append(sql.SQL("upper({}) = ANY(%s)").format(sql.Identifier(sym_col)))
                params.append(allowed_vals)

            where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
            tbl = sql.Identifier(self.schema, table)

            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT MAX({}) AS max_ts FROM {}{}").format(sql.Identifier(ts_col), tbl, where_sql), params)
                row = cur.fetchone()
                max_ts = row[0] if row else None

            if not max_ts:
                _update_latest(datetime.min)
                return {}

            params2 = list(params) + [str(max_ts)]
            where2 = where_sql + sql.SQL(" AND {} = %s").format(sql.Identifier(ts_col))

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("SELECT * FROM {}{}").format(tbl, where2), params2)
                rows = cur.fetchall() or []

            max_dt = _parse_timestamp(str(max_ts))
            _update_latest(max_dt)

            latest: Dict[str, Dict] = {}
            for r in rows:
                sym = str(r.get(sym_col, "") or "").upper()
                if not sym:
                    continue
                if allowed and sym not in allowed:
                    continue
                if sym not in latest:
                    latest[sym] = dict(r)
            return latest
        except Exception as exc:
            LOGGER.warning("PG 读取基础数据失败(field=%s): %s", field, exc)
            return {}
        finally:
            self._return_conn(conn)

    def fetch_metric(self, table: str, period: str) -> List[Dict]:
        table = self._resolve_table(table)
        cols = self._table_columns(table)
        if not cols:
            return []

        ts_col = self._pick_ts_col(cols) or "数据时间"
        sym_col = "交易对" if "交易对" in cols else (self._pick_symbol_col(cols) or "交易对")
        period_cols = [c for c in cols if str(c).lower() in ("周期", "period", "interval")]
        period_vals = self._period_candidates(period)
        allowed = _get_allowed_symbols()
        allowed_vals = sorted({s.upper() for s in (allowed or set())}) if allowed else []

        conn = self._get_conn()
        if conn is None:
            return []
        try:
            from psycopg import sql  # type: ignore
            from psycopg.rows import dict_row  # type: ignore

            clauses: list[sql.Composed] = []
            params: list[object] = []

            if period_cols:
                sub = []
                for c in period_cols:
                    sub.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(c)))
                    params.append(period_vals)
                clauses.append(sql.SQL("(") + sql.SQL(" OR ").join(sub) + sql.SQL(")"))

            if allowed_vals and sym_col in cols:
                clauses.append(sql.SQL("upper({}) = ANY(%s)").format(sql.Identifier(sym_col)))
                params.append(allowed_vals)

            where_sql = sql.SQL("")
            if clauses:
                where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)

            tbl = sql.Identifier(self.schema, table)
            query = sql.SQL(
                "SELECT DISTINCT ON ({sym}) * FROM {tbl}{where} ORDER BY {sym}, {ts} DESC"
            ).format(sym=sql.Identifier(sym_col), tbl=tbl, where=where_sql, ts=sql.Identifier(ts_col))

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = cur.fetchall() or []

            latest_ts: datetime = datetime.min
            out: List[Dict] = []
            for r in rows:
                ts = _parse_timestamp(str(r.get(ts_col, "") or ""))
                if ts > latest_ts:
                    latest_ts = ts
                out.append(dict(r))

            if latest_ts != datetime.min:
                _update_latest(latest_ts)
            return out
        except Exception as exc:
            LOGGER.warning("PG 读取表失败: %s.%s: %s", self.schema, table, exc)
            return []
        finally:
            self._return_conn(conn)

    def _fetch_single_row(self, table: str, period: str, symbol: str) -> Dict:
        table = self._resolve_table(table)
        cols = self._table_columns(table)
        if not cols:
            return {}

        sym_full = (symbol or "").strip().upper()
        sym_with_usdt = sym_full if sym_full.endswith("USDT") else sym_full + "USDT"
        sym_base = sym_full.replace("USDT", "")
        period_vals = self._period_candidates(period)
        ts_col = self._pick_ts_col(cols) or "数据时间"

        conn = self._get_conn()
        if conn is None:
            return {}
        try:
            from psycopg import sql  # type: ignore
            from psycopg.rows import dict_row  # type: ignore

            sym_conds: list[sql.Composed] = []
            params: list[object] = []

            if "交易对" in cols:
                sym_conds.append(
                    sql.SQL("(upper({})=%s OR replace(upper({}),'USDT','')=%s)").format(
                        sql.Identifier("交易对"), sql.Identifier("交易对")
                    )
                )
                params.extend([sym_with_usdt, sym_base])
            if "币种" in cols:
                sym_conds.append(sql.SQL("upper({})=%s").format(sql.Identifier("币种")))
                params.append(sym_base)
            if "symbol" in cols:
                sym_conds.append(sql.SQL("upper({})=%s").format(sql.Identifier("symbol")))
                params.append(sym_base)

            if not sym_conds:
                return {}

            where_parts: list[sql.Composed] = [sql.SQL("(") + sql.SQL(" OR ").join(sym_conds) + sql.SQL(")")]

            period_cols = [c for c in cols if str(c).lower() in ("周期", "period", "interval")]
            if period_cols:
                sub = []
                for c in period_cols:
                    sub.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(c)))
                    params.append(period_vals)
                where_parts.append(sql.SQL("(") + sql.SQL(" OR ").join(sub) + sql.SQL(")"))

            where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_parts)
            order_sql = sql.SQL(" ORDER BY {} DESC, ctid DESC LIMIT 1").format(sql.Identifier(ts_col))

            tbl = sql.Identifier(self.schema, table)
            query = sql.SQL("SELECT * FROM {}{}{}").format(tbl, where_sql, order_sql)

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as exc:
            LOGGER.warning("PG 单行查询失败: %s.%s: %s", self.schema, table, exc)
            return {}
        finally:
            self._return_conn(conn)

    def fetch_base_row(self, period: str, symbol: str) -> Dict:
        return self._fetch_single_row("基础数据", period, symbol)

    def fetch_row(self, table: str, period: str, symbol: str, *,
                  symbol_keys: tuple = ("交易对", "币种", "symbol"),
                  base_fields: Optional[List[str]] = None) -> Dict:
        row = self._fetch_single_row(table, period, symbol)
        if not row:
            return {}
        base = self.fetch_base_row(period, symbol) or {}
        sym = symbol.upper()
        merged = dict(row)
        merged["symbol"] = sym
        merged["price"] = float(base.get("当前价格", row.get("当前价格", 0)) or 0)
        merged["quote_volume"] = float(base.get("成交额", row.get("成交额", 0)) or 0)
        merged["change_percent"] = float(base.get("变化率", 0) or 0)
        merged["updated_at"] = base.get("数据时间") or row.get("数据时间")
        for k in ["振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比"]:
            if k in base:
                merged[k] = base.get(k)
        if base_fields:
            for bf in base_fields:
                if bf in base:
                    merged[bf] = base.get(bf)
        return merged

    def merge_with_base(self, table: str, period: str,
                        symbol_keys: tuple = ("交易对", "币种", "symbol"),
                        base_fields: Optional[List[str]] = None) -> List[Dict]:
        metrics = self.fetch_metric(table, period)
        if not metrics:
            return []
        base_map = self.fetch_base(period)
        merged: List[Dict] = []
        for r in metrics:
            sym = ""
            for key in symbol_keys:
                val = r.get(key)
                if val:
                    sym = str(val).upper()
                    break
            if not sym:
                continue
            base = base_map.get(sym, {})
            row = dict(r)
            row["symbol"] = sym
            row["price"] = float(base.get("当前价格", r.get("当前价格", 0)) or 0)
            row["quote_volume"] = float(base.get("成交额", r.get("成交额", 0)) or 0)
            row["change_percent"] = float(base.get("变化率", 0) or 0)
            row["updated_at"] = base.get("数据时间") or r.get("数据时间")
            for k in ["振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比"]:
                if k in base:
                    row[k] = base.get(k)
            if base_fields:
                for bf in base_fields:
                    if bf in base:
                        row[bf] = base.get(bf)
            merged.append(row)
        return merged

    def get_volume_rows(self, period: str) -> List[Dict]:
        metric_rows = self.fetch_metric("Volume", period)
        if not metric_rows:
            return []
        base_map = self.fetch_base(period)
        merged: List[Dict] = []
        for r in metric_rows:
            sym = str(r.get("交易对", "")).upper()
            if not sym:
                continue
            base = base_map.get(sym, {})
            merged.append({
                "symbol": sym,
                "quote_volume": float(base.get("成交额", 0) or 0),
                "base_volume": float(r.get("成交量", 0) or base.get("成交量", 0) or 0),
                "last_close": float(base.get("当前价格", 0) or 0),
                "first_close": float(base.get("开盘价", 0) or 0),
                "change_percent": float(base.get("变化率", 0) or 0) * 100 if abs(float(base.get("变化率", 0) or 0)) < 1 else float(base.get("变化率", 0) or 0),
                "ma5_volume": float(r.get("MA5成交量", 0) or 0),
                "ma20_volume": float(r.get("MA20成交量", 0) or 0),
                "updated_at": base.get("数据时间") or r.get("数据时间"),
            })
        return merged

    def get_atr_rows(self, period: str) -> List[Dict]:
        metrics = self.fetch_metric("ATR波幅榜单", period)
        if not metrics:
            return []
        base_map = self.fetch_base(period)
        out: List[Dict] = []
        for r in metrics:
            sym = str(r.get("交易对", r.get("币种", ""))).upper()
            if not sym:
                continue
            base = base_map.get(sym, {})
            out.append({
                "symbol": sym,
                "strength": float(r.get("强度", 0) or 0),
                "atr_pct": float(r.get("ATR百分比", 0) or 0),
                "price": float(base.get("当前价格", r.get("当前价格", 0)) or 0),
                "category": r.get("波动分类") or "-",
                "quote_volume": float(base.get("成交额", 0) or 0),
                "updated_at": (base.get("数据时间") or r.get("数据时间")),
            })
        return out


def _resolve_indicator_read_source() -> str:
    """
    指标读取来源：
    - INDICATOR_READ_SOURCE=sqlite|pg|auto（默认 auto）
    - auto 规则：跟随 INDICATOR_STORE_MODE（pg/dual => pg；否则 sqlite）
    """
    raw = (os.environ.get("INDICATOR_READ_SOURCE") or "auto").strip().lower()
    if raw in {"sqlite", "pg"}:
        return raw
    store_mode = (os.environ.get("INDICATOR_STORE_MODE") or "pg").strip().lower()
    return "pg" if store_mode in {"pg", "dual"} else "sqlite"


_PROVIDER: Optional[object] = None
_PROVIDER_SOURCE: str | None = None


def get_ranking_provider():
    global _PROVIDER, _PROVIDER_SOURCE
    source = _resolve_indicator_read_source()
    if _PROVIDER is None or _PROVIDER_SOURCE != source:
        if source == "pg":
            try:
                _PROVIDER = PgRankingDataProvider()
                _PROVIDER_SOURCE = "pg"
            except Exception as exc:
                LOGGER.warning("PG provider 初始化失败，将回退到 SQLite: %s", exc)
                _PROVIDER = RankingDataProvider()
                _PROVIDER_SOURCE = "sqlite"
        else:
            _PROVIDER = RankingDataProvider()
            _PROVIDER_SOURCE = "sqlite"
    return _PROVIDER


__all__ = ["RankingDataProvider", "PgRankingDataProvider", "get_ranking_provider", "format_symbol"]
