#! /usr/bin/env python3
# futures_demo/demo.py
"""
一键演示脚本：快速验证 akshare 数据流水线
1. 安装依赖
2. 拉取指定品种的分钟K线
3. 存入 SQLite
4. 展示数据质量报告
5. 输出样例数据可视化摘要

用法：
    python demo.py [symbol]

示例：
    python demo.py                # 默认拉取配置中的所有品种
    python demo.py RB2410         # 只拉取螺纹钢2410
"""

from __future__ import annotations
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess

# 确保能导入自己
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from futures_demo.config import load_config
from futures_demo.fetcher import fetch_minute_bars
from futures_demo.storage import create_storage
from futures_demo.models import MarketBar, DataSource, Exchange
from futures_demo.quality import generate_report


def print_bar_sample(bars: list[MarketBar], n: int = 5):
    """打印前 n 条 K线 样例"""
    if not bars:
        print("  (no data)")
        return

    print(f"  {'symbol':12s} {'time':20s} {'open':>10s} {'high':>10s} {'low':>10s} {'close':>10s} {'vol':>8s}")
    print("  " + "-" * 80)
    for bar in bars[:n]:
        dt = bar.ts_dt.strftime("%Y-%m-%d %H:%M")
        print(
            f"  {bar.symbol:12s} {dt:20s}"
            f" {str(bar.open)[:10]:>10s} {str(bar.high)[:10]:>10s}"
            f" {str(bar.low)[:10]:>10s} {str(bar.close)[:10]:>10s}"
            f" {bar.volume:>8d}"
        )


def run_demo(symbols: list[str]):
    """执行完整演示流程"""
    print("=" * 72)
    print("  [Futures Minute Bar Pipeline Demo (AKShare)]")
    print("=" * 72)

    # 1. 初始化存储
    db_path = Path(__file__).parent / "data" / "futures_1m.db"
    db_path.parent.mkdir(exist_ok=True)

    from futures_demo.storage import SQLiteStorage
    storage = SQLiteStorage(str(db_path))
    print(f"\n[Storage] SQLite @ {db_path}")

    total_bars = 0
    all_bars = []

    # 2. 逐品种拉取
    print(f"\n[Fetch] {len(symbols)} symbols from akshare/Sina...")
    print()

    for sym in symbols:
        print(f"  ── {sym} ", end="")
        sys.stdout.flush()

        try:
            bars = fetch_minute_bars(sym, lookback_days=3)
        except Exception as e:
            print(f"[FAIL] {e}")
            continue

        if not bars:
            print("(no data)")
            continue

        # 存入 SQLite
        n = storage.upsert_bars(bars)
        total_bars += n
        all_bars.extend(bars)
        print(f"[OK] {len(bars)} bars (upserted {n})")

        time.sleep(0.3)  # 礼貌延迟

    # 3. 验证
    print(f"\n[Total] {total_bars} bars stored")
    print()

    # 按品种分组打印样例
    seen_symbols = set()
    for bar in all_bars:
        if bar.symbol not in seen_symbols:
            seen_symbols.add(bar.symbol)
            print(f"\n  Symbol: {bar.symbol}")
            sample_bars = [b for b in all_bars if b.symbol == bar.symbol][:3]
            print_bar_sample(sample_bars)

    # 4. 质量报告
    print(f"\n[Quality Report]:")
    print()

    for symbol in sorted(seen_symbols):
        import time as _time
        end_ns = _time.time_ns()
        start_ns = end_ns - 7 * 24 * 3600 * int(1e9)
        bars = storage.query_bars(symbol, start_ns, end_ns)

        if not bars:
            continue

        report = generate_report(bars)
        status = "[OK]" if report.is_healthy else "[BAD]"
        print(
            f"  {status} {symbol:20s}"
            f" bars={report.total_bars:4d}"
            f" gaps={report.gap_count:2d}"
            f" max_gap={report.max_gap_seconds:6.0f}s"
            f" outliers={report.outlier_count:2d}"
            f" zero_vol={report.zero_volume_count:3d}"
        )

    # 5. DB 文件大小
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"\n[DB size]: {size_mb:.2f} MB")

    storage.close()
    print(f"\n{'=' * 72}")
    print(f"  [OK] Demo complete! Run 'python -m futures_demo.pipeline loop' for continuous collection")
    print(f"  [OK] Run 'python -m futures_demo.pipeline verify' for detailed quality checks")
    print(f"{'=' * 72}")


def main():
    cfg = load_config(str(Path(__file__).parent / "config.yaml"))
    symbols = sys.argv[1:] if len(sys.argv) > 1 else cfg.symbols.symbols
    run_demo(symbols)


if __name__ == "__main__":
    main()