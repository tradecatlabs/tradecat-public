"""支持币种路由 (对齐 CoinGlass /api/futures/supported-coins)"""

import os
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from psycopg import sql

from src.config import get_pg_pool
from src.utils.errors import ErrorCode, api_response, error_response
from src.utils.symbol import to_base_symbol

# 添加 repo root 到路径，以使用 assets/common/symbols.py 的全局币种管理
repo_root = Path(__file__).resolve().parents[5]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from assets.common.symbols import get_configured_symbols

router = APIRouter(tags=["futures"])

BASE_TABLE = "基础数据同步器.py"


@router.get("/supported-coins")
async def get_supported_coins() -> dict:
    """获取支持的币种列表 (继承全局 SYMBOLS_GROUPS 配置)"""
    
    # 优先使用全局配置的币种
    configured = get_configured_symbols()
    if configured:
        # 转换为 CoinGlass 格式 (BTC 而非 BTCUSDT)
        symbols = sorted(set(to_base_symbol(s) for s in configured))
        return api_response(symbols)
    
    # auto/all 模式: 从数据库获取实际可用币种（优先 PG）
    schema = (os.environ.get("INDICATOR_PG_SCHEMA") or "tg_cards").strip() or "tg_cards"

    def _fetch_symbols_pg():
        pool = get_pg_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                    (schema, BASE_TABLE),
                )
                if not cur.fetchone():
                    raise RuntimeError(f"PG 基础数据表不存在: {schema}.{BASE_TABLE}")
                cur.execute(
                    sql.SQL('SELECT DISTINCT "交易对" FROM {} ORDER BY "交易对"').format(sql.Identifier(schema, BASE_TABLE))
                )
                rows = cur.fetchall() or []
        symbols = [to_base_symbol(r[0]) for r in rows if r and r[0]]
        return sorted(set(symbols))

    try:
        symbols = await run_in_threadpool(_fetch_symbols_pg)
        return api_response(symbols)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f"查询失败: {e}")
