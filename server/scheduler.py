# server/scheduler.py
"""
定时调度器
- 每分钟触发数据轮询
- 轮询完成后自动通过 ConnectionManager 广播新数据
- 支持手动触发单次刷新
- 每日 23:59 自动拉取所有品种主力合约数据
"""

from __future__ import annotations
import asyncio
from datetime import datetime
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
    - 每日 23:59 自动拉取所有品种主力合约分钟数据
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
        self._daily_done = False

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

    async def _run_poll(self, trading_hours_only: bool) -> dict[str, list[dict]]:
        """在 executor 中运行同步的 poll_new_data，不阻塞事件循环"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._data.poll_new_data, trading_hours_only
        )

    async def _tick(self):
        """一次调度 tick：轮询 → 推送到已订阅客户端"""
        logger.debug("Scheduler tick...")

        # ── 每日 23:59 主力合约数据拉取 ──
        now = datetime.now()
        if now.hour == 23 and now.minute == 59 and not self._daily_done:
            logger.info("[daily] 23:59 - starting dominant contract data pull...")
            await self._run_daily_pull()
            self._daily_done = True
        if now.hour != 23:
            self._daily_done = False

        # ── 常规分钟级轮询 ──
        await self._ws.broadcast_status("polling", "Fetching new data...")

        # 1. 轮询新数据（在 executor 中运行，不阻塞事件循环）
        new_data = await self._run_poll(trading_hours_only=self._trading_only)

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

    async def _run_daily_pull(self):
        """
        每日 23:59 执行：遍历所有品种，拉取当前主力合约分钟数据。
        在 executor 中运行以避免阻塞事件循环。
        """
        # 动态导入避免循环依赖
        from futures_demo.config import get_config as get_data_config
        from futures_demo.fetcher import parse_symbol, fetch_minute_bars, SINA_MAX_LOOKBACK_DAYS
        from server.dominant import resolve_dominant_symbol

        cfg = get_data_config()
        symbols_cfg = cfg.symbols.symbols
        logger.info(f"[daily] Pulling dominant contract data for {len(symbols_cfg)} varieties...")

        total = 0
        loop = asyncio.get_running_loop()

        for sym in symbols_cfg:
            variety, _ = parse_symbol(sym)

            # 在 executor 中解析主力合约（AKShare 同步调用）
            dom_symbol = await loop.run_in_executor(None, resolve_dominant_symbol, variety)
            if not dom_symbol:
                logger.warning(f"[daily] Cannot resolve dominant for {variety}, skip")
                continue

            code = dom_symbol.split(".")[0]
            logger.info(f"[daily] {variety} -> dominant: {code}")

            # 在 executor 中拉取分钟数据（Sina 最多返回 SINA_MAX_LOOKBACK_DAYS 天）
            bars = await loop.run_in_executor(
                None, lambda: fetch_minute_bars(code, lookback_days=SINA_MAX_LOOKBACK_DAYS, force=True)
            )

            if bars:
                n = self._data.storage.upsert_bars(bars)
                total += n
                logger.info(f"[daily] {code}: {len(bars)} bars, {n} upserted")

            # 礼貌延迟，避免频控
            await asyncio.sleep(0.3)

        logger.info(f"[daily] Done. Total {total} bars upserted across {len(symbols_cfg)} varieties")
        await self._ws.broadcast_status("idle", f"Daily pull: {total} bars")

    async def trigger_poll(self) -> dict[str, int]:
        """
        手动触发一轮完整的拉取+推送。
        返回 {symbol: bars_count}
        """
        logger.info("Manual refresh triggered")
        await self._ws.broadcast_status("polling", "Manual refresh...")

        result = {}
        # 在 executor 中运行，不阻塞事件循环
        new_data = await self._run_poll(trading_hours_only=False)

        for symbol, bars in new_data.items():
            result[symbol] = len(bars)
            await self._ws.broadcast_kline_update(symbol, bars)

        await self._ws.broadcast_status("idle", f"Manual refresh: {len(new_data)} symbols")
        logger.info(f"Manual refresh complete: {sum(result.values())} bars")
        return result

    @property
    def is_running(self) -> bool:
        return self._running
