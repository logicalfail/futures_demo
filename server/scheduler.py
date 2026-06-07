# server/scheduler.py
"""
定时调度器
- 每分钟触发数据轮询
- 轮询完成后自动通过 ConnectionManager 广播新数据
- 支持手动触发单次刷新
"""

from __future__ import annotations
import asyncio
import time
from typing import Optional

from loguru import logger

from server.connection_manager import ConnectionManager
from server.data_service import DataService


class DataScheduler:
    """
    数据调度器
    - start() 启动后台循环
    - stop() 优雅停止
    - trigger_poll() 手动触发一轮轮询
    """

    def __init__(
        self,
        data_service: DataService,
        connection_manager: ConnectionManager,
        interval_seconds: int = 60,
        trading_hours_only: bool = True,
    ):
        self._data = data_service
        self._ws = connection_manager
        self._interval = interval_seconds
        self._trading_only = trading_hours_only
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """启动后台调度循环"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Scheduler started (interval={self._interval}s)")

    async def stop(self):
        """停止调度"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

    async def _run_loop(self):
        """调度主循环"""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await self._ws.broadcast_status("error", f"Scheduler: {e}")

            # 等待下一个周期
            for _ in range(self._interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

        logger.info("Scheduler loop ended")

    async def _tick(self):
        """一次调度 tick：轮询 → 推送到已订阅客户端"""
        logger.debug("Scheduler tick...")
        await self._ws.broadcast_status("polling", "Fetching new data...")

        # 1. 轮询新数据
        new_data = self._data.poll_new_data(trading_hours_only=self._trading_only)

        if not new_data:
            logger.debug("No new data")
            await self._ws.broadcast_status("idle", "No new data")
            return

        # 2. 广播到已订阅的连接
        total_broadcast = 0
        for symbol, bars in new_data.items():
            # 只推给订阅了该品种的连接
            n = await self._ws.broadcast_kline_update(symbol, bars)
            total_broadcast += n

        await self._ws.broadcast_status("idle", f"Updated {len(new_data)} symbols")

    async def trigger_poll(self) -> dict[str, int]:
        """
        手动触发一轮完整的拉取+推送。
        返回 {symbol: bars_count}
        """
        logger.info("Manual refresh triggered")
        await self._ws.broadcast_status("polling", "Manual refresh...")

        result = {}
        new_data = self._data.poll_new_data(trading_hours_only=False)

        for symbol, bars in new_data.items():
            result[symbol] = len(bars)
            await self._ws.broadcast_kline_update(symbol, bars)

        await self._ws.broadcast_status("idle", f"Manual refresh: {len(new_data)} symbols")
        logger.info(f"Manual refresh complete: {sum(result.values())} bars")
        return result

    @property
    def is_running(self) -> bool:
        return self._running
