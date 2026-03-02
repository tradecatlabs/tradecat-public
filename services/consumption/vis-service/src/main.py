"""
vis-service 入口。

提供最小可运行的 FastAPI 应用，包含：
- /health 健康检查
- /templates 模板列表
- /render 渲染示例折线图
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.routes import router
from core.settings import get_settings


def create_app() -> FastAPI:
    """构建 FastAPI 实例并注册路由。"""

    app = FastAPI(title="TradeCat Visualization Service", version="0.1.0")
    app.include_router(router, prefix="")

    @app.middleware("http")
    async def add_settings_header(request: Request, call_next):
        """在响应头中附加服务名，便于排查。"""

        response = await call_next(request)
        settings = get_settings()
        response.headers["X-Service"] = settings.service_name
        return response

    return app


app = create_app()

# 统一日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception):
    """兜底异常处理，避免泄露堆栈到客户端。"""

    logging.exception("未捕获异常: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "内部错误"})


def run_server():
    """Console script 入口点"""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run_server()
