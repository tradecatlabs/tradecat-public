"""FastAPI 应用 (对齐 CoinGlass V4 规范)"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from src import __version__
from src.routers import (
    health_router,
    coins_router,
    ohlc_router,
    open_interest_router,
    funding_rate_router,
    futures_metrics_router,
    base_data_router,
    indicator_router,
    signal_router,
    query_v1_router,
)
from src.utils.errors import ErrorCode

app = FastAPI(
    title="TradeCat API",
    description="对外数据消费 REST API 服务 (CoinGlass V4 风格)",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 统一异常处理 (对齐 CoinGlass V4 响应格式)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验错误处理"""
    errors = exc.errors()
    if errors:
        first_error = errors[0]
        field = ".".join(str(loc) for loc in first_error.get("loc", []))
        msg = f"参数错误: {field} - {first_error.get('msg', 'invalid')}"
    else:
        msg = "参数校验失败"
    
    return JSONResponse(
        status_code=400,
        content={
            "code": ErrorCode.PARAM_ERROR.value,
            "msg": msg,
            "data": None,
            "success": False
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理"""
    return JSONResponse(
        status_code=500,
        content={
            "code": ErrorCode.INTERNAL_ERROR.value,
            "msg": f"服务器错误: {str(exc)}",
            "data": None,
            "success": False
        }
    )

# 注册路由 (对齐 CoinGlass 路径风格)
app.include_router(health_router, prefix="/api")
app.include_router(coins_router, prefix="/api/futures")
app.include_router(ohlc_router, prefix="/api/futures")
app.include_router(open_interest_router, prefix="/api/futures")
app.include_router(funding_rate_router, prefix="/api/futures")
app.include_router(futures_metrics_router, prefix="/api/futures")
app.include_router(base_data_router, prefix="/api/futures")
app.include_router(indicator_router, prefix="/api")
app.include_router(signal_router, prefix="/api")
app.include_router(query_v1_router, prefix="/api/v1")
