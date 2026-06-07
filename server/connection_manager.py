# server/connection_manager.py
"""
WebSocket 连接管理器
- 连接池管理（连接 ↔ 订阅品种映射）
- 按品种广播消息
- 心跳保活（30秒 ping）
"""

from __future__ import annotations
import asyncio
import json
import time
from collections import defaultdict
from typing import Optional

from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    """
    WebSocket 连接池

    active_connections: {
        websocket: {symbol1, symbol2, ...}  # 该连接订阅的品种
    }
    """

    def __init__(self):
        self._connections: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        """接受新 WebSocket 连接"""
        await ws.accept()
        async with self._lock:
            self._connections[ws] = set()
        logger.info(f"WS connected: {ws.client}  (total: {len(self._connections)})")

    async def disconnect(self, ws: WebSocket) -> None:
        """断开连接，清理订阅"""
        async with self._lock:
            self._connections.pop(ws, None)
        logger.info(f"WS disconnected: {ws.client}  (total: {len(self._connections)})")

    async def subscribe(self, ws: WebSocket, symbols: list[str]) -> None:
        """客户端订阅品种"""
        async with self._lock:
            if ws in self._connections:
                self._connections[ws].update(symbols)
                logger.debug(f"Subscribed {symbols} for {ws.client}")

    async def unsubscribe(self, ws: WebSocket, symbols: list[str]) -> None:
        """客户端取消订阅"""
        async with self._lock:
            if ws in self._connections:
                self._connections[ws].difference_update(symbols)
                logger.debug(f"Unsubscribed {symbols} for {ws.client}")

    async def broadcast_kline_update(self, symbol: str, bars: list[dict]) -> int:
        """
        向所有订阅了该 symbol 的连接广播 K线更新。
        Returns: 接收到的连接数
        """
        message = json.dumps({
            "type": "kline_update",
            "symbol": symbol,
            "bars": bars,
        })
        received = 0
        async with self._lock:
            for ws, subs in list(self._connections.items()):
                if symbol in subs:
                    try:
                        await ws.send_text(message)
                        received += 1
                    except Exception:
                        # 发送失败，连接可能已断开
                        self._connections.pop(ws, None)
        if received:
            logger.debug(f"Broadcast {symbol}: {len(bars)} bars to {received} clients")
        return received

    async def broadcast_status(self, status: str, message: str = "") -> int:
        """向所有连接广播状态消息"""
        payload = json.dumps({"type": "status", "status": status, "message": message})
        sent = 0
        async with self._lock:
            for ws in list(self._connections.keys()):
                try:
                    await ws.send_text(payload)
                    sent += 1
                except Exception:
                    self._connections.pop(ws, None)
        return sent

    async def broadcast_error(self, msg: str) -> int:
        """向所有连接广播错误消息"""
        return await self.broadcast_status("error", msg)

    async def send_to(self, ws: WebSocket, data: dict) -> bool:
        """向指定连接发送消息"""
        try:
            await ws.send_json(data)
            return True
        except Exception:
            await self.disconnect(ws)
            return False

    @property
    def total(self) -> int:
        return len(self._connections)

    def get_subscribed_symbols(self) -> set[str]:
        """获取所有连接订阅的品种合集"""
        symbols: set[str] = set()
        for subs in self._connections.values():
            symbols.update(subs)
        return symbols

    async def heartbeat_loop(self, interval: int = 30):
        """心跳保活：每隔 interval 秒 ping 所有连接"""
        while True:
            await asyncio.sleep(interval)
            async with self._lock:
                for ws in list(self._connections.keys()):
                    try:
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        self._connections.pop(ws, None)
