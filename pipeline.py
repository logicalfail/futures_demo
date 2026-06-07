# futures_demo/pipeline.py
"""
数据流水线主入口
- fetch: 从 akshare 获取分钟数据
- normalize: 统一 MarketBar 格式
- store: upsert 到 SQLite/TimescaleDB
- verify: 数据质量检查 + 覆盖率报告

可用模式：
  python -m futures_demo.pipeline fetch     # 单次拉取+存储
  python -m futures_demo.pipeline loop      # 持续循环采集（分钟级）
  python -m futures_demo.pipeline verify    # 数据质量验证
"""

from __future__ import annotations
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

from .config import load_config, get_config
from .fetcher import fetch_minute_bars, fetch_all_symbols
from .storage import create_storage, StorageBackend
from .quality import generate_report
from .models import MarketBar


# ============ 单次采集 ============
def run_fetch() -> int:
    """
    单次采集全流程：fetch → normalize → upsert
    返回写入的 K线 数量
    """
    cfg = get_config()
    storage = create_storage()
    total = 0

    try:
        for bar in fetch_all_symbols(cfg.symbols.symbols, cfg.source.lookback_days):
            try:
                n = storage.upsert_bars([bar])
                if n > 0:
                    total += 1
            except Exception as e:
                logger.error(f"Storage upsert failed for {bar.symbol}@{bar.ts_ns}: {e}")

        logger.info(f"[OK] Fetch complete: upserted {total} bars into {cfg.storage.type}")
    finally:
        storage.close()

    return total


def run_fetch_incremental() -> int:
    """
    增量采集：仅拉取最新数据（跳过已有时间戳）
    适合循环调度
    """
    cfg = get_config()
    storage = create_storage()
    total = 0

    try:
        for symbol in cfg.symbols.symbols:
            latest_ts = storage.get_latest_ts(f"{symbol}.{get_exchange_from_symbol(symbol).value}")
            bars = fetch_minute_bars(symbol, lookback_days=1)

            new_bars = []
            for bar in bars:
                if latest_ts is None or bar.ts_ns > latest_ts:
                    new_bars.append(bar)

            if new_bars:
                n = storage.upsert_bars(new_bars)
                total += n
                logger.info(f"  {symbol}: {len(new_bars)} new bars (latest was {latest_ts})")
            else:
                logger.info(f"  {symbol}: no new data")

            time.sleep(0.3)  # 礼貌延迟

        logger.info(f"[OK] Incremental fetch complete: upserted {total} new bars")
    finally:
        storage.close()

    return total


def get_exchange_from_symbol(symbol: str):
    """工具函数：从配置获取交易所"""
    from .fetcher import parse_symbol, get_exchange
    variety, _ = parse_symbol(symbol)
    return get_exchange(variety)


# ============ 数据验证 ============
def run_verify() -> int:
    """验证已存储数据质量"""
    cfg = get_config()
    storage = create_storage()
    all_healthy = True
    total_bars = 0

    try:
        n_days = cfg.source.lookback_days
        end_ns = time.time_ns()
        start_ns = end_ns - n_days * 24 * 3600 * int(1e9)

        for symbol_cfg in cfg.symbols.symbols:
            full_symbol = f"{symbol_cfg}.{get_exchange_from_symbol(symbol_cfg).value}"
            bars = storage.query_bars(full_symbol, start_ns, end_ns)

            if not bars:
                logger.warning(f"[WARN] No data for {full_symbol}")
                continue

            report = generate_report(bars)
            total_bars += report.total_bars

            status = "[OK]" if report.is_healthy else "[BAD]"
            print(
                f"{status} {full_symbol:20s} "
                f"bars={report.total_bars:4d} "
                f"gaps={report.gap_count:2d} "
                f"max_gap={report.max_gap_seconds:5.0f}s "
                f"outliers={report.outlier_count:2d} "
                f"zero_vol={report.zero_volume_count:3d}"
            )

            if not report.is_healthy:
                all_healthy = False

        print(f"\nTotal: {total_bars} bars across {len(cfg.symbols.symbols)} symbols")
        print(f"Health: {'[OK] ALL GOOD' if all_healthy else '[BAD] ISSUES FOUND'}")
    finally:
        storage.close()

    return 0 if all_healthy else 1


# ============ 循环采集（调度） ============
def run_loop(interval_seconds: Optional[int] = None):
    """
    持续循环采集
    - 只在交易时段工作
    - 每次间隔 interval_seconds 秒
    - 支持 Ctrl+C 优雅退出
    """
    cfg = get_config()
    interval = interval_seconds or cfg.scheduler.interval_seconds

    logger.info(f"🚀 Starting data pipeline loop (interval={interval}s)")
    logger.info(f"   Symbols: {cfg.symbols.symbols}")
    logger.info(f"   Storage: {cfg.storage.type} @ {cfg.storage.path}")
    logger.info("   Press Ctrl+C to stop gracefully\n")

    iteration = 0
    total_upserted = 0

    while True:
        try:
            iteration += 1
            now = datetime.now()
            logger.info(f"[iter {iteration}] {now.strftime('%Y-%m-%d %H:%M:%S')}")

            n = run_fetch_incremental()
            if n > 0:
                total_upserted += n

            # 每个小时做一次质量检查
            if iteration % (3600 // interval) == 0:
                logger.info("🔄 Running hourly quality check...")
                run_verify()

            logger.info(f"   Running total upserted: {total_upserted} bars")
            time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("\n👋 Graceful shutdown")
            break
        except Exception as e:
            logger.error(f"Loop iteration failed: {e}", exc_info=True)
            logger.info(f"Retrying in {interval}s...")
            time.sleep(interval)


# ============ CLI ============
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    load_config()

    if cmd == "fetch":
        n = run_fetch()
        print(f"\nDone. {n} bars stored.")
    elif cmd == "incremental":
        n = run_fetch_incremental()
        print(f"\nDone. {n} new bars stored.")
    elif cmd == "verify":
        sys.exit(run_verify())
    elif cmd == "loop":
        # 可选传间隔秒数
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else None
        run_loop(interval)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()