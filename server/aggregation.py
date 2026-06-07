"""K线周期聚合：将1m原始数据聚合为 5m / 15m / 1h / 1d"""

from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal


Period = Literal["1m", "5m", "15m", "1h", "1d"]


def aggregate_bars(bars: list[dict], period: Period) -> list[dict]:
    """
    将1分钟K线聚合为目标周期。
    bars: [{ts_ns, open, high, low, close, volume, open_interest, ...}, ...]
    返回: [{ts_ns, ts, open, high, low, close, volume, open_interest}, ...]
    """
    if period == "1m" or not bars:
        return bars

    group_key_fn = _grouper(period)
    groups: dict[int, dict] = {}

    for bar in bars:
        dt = datetime.fromtimestamp(bar["ts_ns"] / 1e9)
        key = int(group_key_fn(dt).timestamp() * 1e9)

        if key not in groups:
            groups[key] = {
                "ts_ns": key,
                "ts": datetime.fromtimestamp(key / 1e9).strftime("%Y-%m-%d %H:%M:%S"),
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
                "open_interest": bar.get("open_interest"),
            }
        else:
            g = groups[key]
            g["high"] = max(g["high"], bar["high"])
            g["low"] = min(g["low"], bar["low"])
            g["close"] = bar["close"]
            g["volume"] += bar["volume"]
            # 持仓量取最后一根
            if bar.get("open_interest") is not None:
                g["open_interest"] = bar["open_interest"]

    result = sorted(groups.values(), key=lambda b: b["ts_ns"])
    # 补齐 ts 字段
    for b in result:
        if "ts" not in b:
            b["ts"] = datetime.fromtimestamp(b["ts_ns"] / 1e9).strftime("%Y-%m-%d %H:%M:%S")
    return result


def _grouper(period: Period):
    """返回一个将 datetime 映射到聚合桶开始时间的函数"""
    if period == "5m":
        return lambda dt: dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)
    elif period == "15m":
        return lambda dt: dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
    elif period == "1h":
        return lambda dt: dt.replace(minute=0, second=0, microsecond=0)
    elif period == "1d":
        return lambda dt: dt.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # 1m
        return lambda dt: dt.replace(second=0, microsecond=0)
