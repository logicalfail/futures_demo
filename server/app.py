# server/app.py
"""
FastAPI 主应用
- WebSocket 端点：/ws
- REST API：/api/*
- 前端静态文件：/
"""

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse
from loguru import logger

from server.config import AppConfig, load_config
from server.connection_manager import ConnectionManager
from server.data_service import DataService
from server.scheduler import DataScheduler
from server.routers.v1 import router as v1_router


# ── 工厂方法 ──────────────────────────────────────────────────
def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    cfg = config or load_config()
    app = FastAPI(title="Futures Terminal API", version="0.1.0")

    # 初始化组件
    cm = ConnectionManager()
    ds = DataService(cfg)
    sched = DataScheduler(
        ds, cm,
        interval_seconds=cfg.scheduler.interval_seconds,
        trading_hours_only=cfg.scheduler.trading_hours_only,
    )

    # 挂载到 app.state 以便访问
    app.state.cfg = cfg
    app.state.cm = cm
    app.state.ds = ds
    app.state.sched = sched

    # ============ WebSocket 端点 ============
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await cm.connect(ws)

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await cm.send_to(ws, {"type": "error", "message": "Invalid JSON"})
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "subscribe":
                    symbols = msg.get("symbols", [])
                    await cm.subscribe(ws, symbols)
                    # 订阅后立即推送该品种的最新数据
                    for sym in symbols:
                        bars = ds.get_latest_bars(sym, 100)
                        if bars:
                            await cm.send_to(ws, {
                                "type": "kline_update",
                                "symbol": sym,
                                "bars": bars,
                            })
                    logger.info(f"Subscribed {ws.client} to {symbols}")

                elif msg_type == "unsubscribe":
                    symbols = msg.get("symbols", [])
                    await cm.unsubscribe(ws, symbols)
                    logger.info(f"Unsubscribed {ws.client} from {symbols}")

                elif msg_type == "manual_refresh":
                    # 手动触发刷新
                    await sched.trigger_poll()

                elif msg_type == "ping":
                    await cm.send_to(ws, {"type": "pong"})

                else:
                    await cm.send_to(ws, {"type": "error", "message": f"Unknown type: {msg_type}"})

        except WebSocketDisconnect:
            await cm.disconnect(ws)
        except Exception as e:
            logger.error(f"WS error: {e}")
            await cm.disconnect(ws)

    # ============ REST API ============

    @app.get("/api/symbols")
    async def api_symbols():
        """获取所有可用品种列表"""
        return {"symbols": ds.get_symbols()}

    @app.get("/api/kline/{symbol}")
    async def api_kline(
        symbol: str,
        limit: int = Query(1000, ge=1, le=10000),
        days_back: int = Query(20, ge=1, le=90),
    ):
        """获取历史K线数据"""
        bars = ds.get_kline(symbol, limit, days_back)
        return {"symbol": symbol, "bars": bars, "count": len(bars)}

    @app.get("/api/quote/{symbol}")
    async def api_quote(symbol: str):
        """获取最新报价"""
        bar = ds.get_latest_quote(symbol)
        return {"symbol": symbol, "quote": bar}

    @app.get("/api/quotes")
    async def api_quotes():
        """获取所有品种的最新报价"""
        symbols = ds.get_symbol_codes()
        results = {}
        for sym in symbols:
            bar = ds.get_latest_quote(sym)
            if bar:
                results[sym] = bar
        return {"count": len(results), "quotes": results}

    @app.post("/api/refresh")
    async def api_refresh():
        """手动刷新所有品种"""
        await sched.trigger_poll()
        return {"status": "ok", "message": "Refresh triggered"}

    @app.get("/api/status")
    async def api_status():
        """服务状态"""
        return ds.server_status()

    @app.get("/api/quality")
    async def api_quality():
        """数据质量报告"""
        return {"reports": ds.get_quality_report()}

    # ============ API v1（外部模块数据接口）============
    app.include_router(v1_router)

    # ============ 前端静态文件 ============
    frontend_path = cfg.server.frontend_path

    @app.get("/")
    async def serve_index():
        """serve frontend index.html"""
        index = frontend_path / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"message": "Frontend not built yet. Run: cd frontend && npm install && npm run build"}

    # SPA fallback: 所有未匹配的页面请求返回 index.html
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA 路由回退"""
        # 跳过 API 路径
        if full_path.startswith("api/") or full_path.startswith("ws"):
            return {"error": "Not found"}

        file_path = frontend_path / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))

        # SPA fallback
        index = frontend_path / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "Not found"}

    # ============ 生命周期事件 ============
    @app.on_event("startup")
    async def startup():
        """启动调度器 + 心跳"""
        if cfg.scheduler.enabled:
            await sched.start()
        # 启动心跳协程
        import asyncio
        asyncio.create_task(cm.heartbeat_loop(30))
        logger.info(f"Server started: http://{cfg.server.host}:{cfg.server.port}")

    @app.on_event("shutdown")
    async def shutdown():
        await sched.stop()
        ds.close()
        logger.info("Server shutdown complete")

    return app


# ── 直接运行 ──────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    cfg = load_config()
    uvicorn.run(
        "server.app:create_app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=cfg.server.reload,
        factory=True,
        log_level=cfg.server.log_level.lower(),
    )
