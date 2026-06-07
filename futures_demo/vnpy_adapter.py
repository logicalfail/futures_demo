# futures_demo/vnpy_adapter.py
"""
vnpy 数据接入参考
=================
vnpy 自带的 CTP 接口可直接订阅行情。以下是两种用法：

方案 A：直接用 vnpy 自带的 CTP 接口（需要 CTP 账号）
方案 B：将 akshare 数据注入 vnpy 的数据库管理系统

本文件提供方案 B 的参考实现：将 akshare 分钟线写入 vnpy 的 BarData 格式
"""

from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .models import MarketBar, DataSource

try:
    from vnpy.trader.object import BarData, Exchange as VnpyExchange, Interval
    from vnpy.trader.constant import Direction, Offset, OrderType, Status, Product
    HAS_VNPY = True
except ImportError:
    HAS_VNPY = False


# vnpy 交易所映射
VNPY_EXCHANGE_MAP = {
    "SHFE": "SHFE",
    "DCE": "DCE",
    "CZCE": "CZCE",
    "CFFEX": "CFFEX",
    "INE": "INE",
}

# vnpy 频率映射
VNPY_INTERVAL_MAP = {
    "1m": Interval.MINUTE,
    "5m": Interval.MINUTE_5,
    "15m": Interval.MINUTE_15,
    "30m": Interval.MINUTE_30,
    "60m": Interval.HOUR,
    "1d": Interval.DAILY,
}


def to_vnpy_bar(bar: MarketBar) -> Optional["BarData"]:
    """将 MarketBar 转为 vnpy BarData"""
    if not HAS_VNPY:
        return None

    # 解析 symbol：RB2410.SHFE -> (RB2410, SHFE)
    symbol_parts = bar.symbol.split(".")
    if len(symbol_parts) != 2:
        return None

    symbol, exchange_str = symbol_parts
    exchange = getattr(VnpyExchange, exchange_str, None)
    if exchange is None:
        return None

    interval = VNPY_INTERVAL_MAP.get(bar.freq, Interval.MINUTE)

    return BarData(
        symbol=symbol,
        exchange=exchange,
        datetime=bar.ts_dt,
        interval=interval,
        open_price=float(bar.open),
        high_price=float(bar.high),
        low_price=float(bar.low),
        close_price=float(bar.close),
        volume=float(bar.volume),
        turnover=float(bar.turnover),
        open_interest=bar.open_interest or 0,
        gateway_name="akshare",
    )


def bars_to_vnpy_csv(bars: list[MarketBar], output_path: str) -> int:
    """
    将 MarketBar 列表导出为 vnpy 可导入的 CSV 格式
    列顺序与 vnpy 的 database_manager 兼容
    """
    import csv
    import os

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        # vnpy BarData CSV header
        writer.writerow([
            "symbol", "exchange", "datetime", "interval",
            "open_price", "high_price", "low_price", "close_price",
            "volume", "turnover", "open_interest"
        ])

        for bar in bars:
            writer.writerow([
                bar.symbol.split(".")[0],  # symbol
                bar.exchange.value,          # exchange
                bar.ts_dt.strftime("%Y-%m-%d %H:%M:%S"),  # datetime
                bar.freq,                    # interval
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                float(bar.volume),
                float(bar.turnover),
                bar.open_interest or 0,
            ])

    n_bars = len(bars)
    size_kb = os.path.getsize(output_path) / 1024
    print(f"📤 Exported {n_bars} bars to {output_path} ({size_kb:.1f} KB)")
    return n_bars


# ============ vnpy 数据管理示例 ============
def load_to_vnpy_database(bars: list[MarketBar], db_name: str = "sqlite"):
    """
    将数据导入 vnpy 数据库（需在 vnpy 环境中运行）

    用法：
        from vnpy.trader.database import database_manager
        from vnpy.trader.object import BarData, Exchange, Interval

        # 注册数据库
        database_manager.connect(settings={
            "database": "sqlite",  # 或 "mysql", "postgresql"
            "database_name": "vnpy_data",
        })

        vnpy_bars = [to_vnpy_bar(b) for b in bars if to_vnpy_bar(b)]
        database_manager.save_bar_data(vnpy_bars)
        print(f"Saved {len(vnpy_bars)} bars to vnpy database")
    """
    print(f"[vnpy] Available function: to_vnpy_bar() and bars_to_vnpy_csv()")
    print(f"         Import example: 'from futures_demo.vnpy_adapter import to_vnpy_bar'")
    return None