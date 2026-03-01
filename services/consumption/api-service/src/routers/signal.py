"""信号数据路由"""

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from src.config import get_pg_pool
from src.utils.errors import ErrorCode, api_response, error_response

router = APIRouter(tags=["signal"])


@router.get("/signal/cooldown")
async def get_cooldown_status() -> dict:
    """获取信号冷却状态"""

    def _fetch_rows():
        # 单真相源：PG signal_state.cooldown
        pool = get_pg_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", ("signal_state.cooldown",))
                if cur.fetchone()[0] is None:
                    raise RuntimeError("PG 冷却表不存在：signal_state.cooldown")
                cur.execute("SELECT key, ts_epoch FROM signal_state.cooldown ORDER BY ts_epoch DESC")
                rows = cur.fetchall() or []
        return [
            {
                "key": row[0],
                "timestamp": int(float(row[1] or 0.0) * 1000),
                "expireTime": int(float(row[1] or 0.0) * 1000),
            }
            for row in rows
        ]

    try:
        data = await run_in_threadpool(_fetch_rows)
        return api_response(data)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f"查询失败: {e}")
