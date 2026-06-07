# futures_demo/quality.py
"""
数据质量检查
- 时间连续性（检查缺失的分钟K线）
- 异常值检测（价格跃变、成交量异常）
- 交易时段匹配（确认数据在正确的交易时间范围内）
- 报告生成
"""

from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta
import time
from typing import Optional

from loguru import logger

from .models import MarketBar, QualityReport
from .config import get_config


TRADING_SESSIONS = [
    ("09:00", "10:15"),
    ("10:30", "11:30"),
    ("13:30", "15:00"),
    ("21:00", "23:30"),  # 夜盘
]

# 品种特殊时段（一些品种没有夜盘或时间不同）
SPECIAL_SESSIONS = {
    # 中金所股指
    "IF": [("09:30", "11:30"), ("13:00", "15:00")],
    "IH": [("09:30", "11:30"), ("13:00", "15:00")],
    "IC": [("09:30", "11:30"), ("13:00", "15:00")],
    "IM": [("09:30", "11:30"), ("13:00", "15:00")],
    # 国债
    "TS": [("09:30", "11:30"), ("13:00", "15:15")],
    "TF": [("09:30", "11:30"), ("13:00", "15:15")],
    "T":  [("09:30", "11:30"), ("13:00", "15:15")],
    "TL": [("09:30", "11:30"), ("13:00", "15:15")],
}


def in_trading_hours(dt: datetime) -> bool:
    """判断一个时间戳是否在交易时段内"""
    import re
    from .fetcher import parse_symbol

    # 简化：不依赖具体品种，用通用时段
    t = dt.strftime("%H:%M")
    for start, end in TRADING_SESSIONS:
        end_dt = datetime.strptime(end, "%H:%M")
        start_dt = datetime.strptime(start, "%H:%M")
        dt_t = datetime.strptime(t, "%H:%M")

        # 处理跨日夜盘
        if start > end:  # e.g. 21:00-23:30, 夜盘不跨日到第二天
            pass  # 简化处理

        if start_dt <= dt_t <= end_dt:
            return True
    return False


def check_gaps(bars: list[MarketBar], max_gap_seconds: int = 120) -> tuple[int, float]:
    """检查分钟K线的时间间隙"""
    if len(bars) < 2:
        return 0, 0.0

    gap_count = 0
    max_gap = 0.0

    for i in range(1, len(bars)):
        # 忽略跨日/午休/夜盘的间隙
        gap_ns = bars[i].ts_ns - bars[i-1].ts_ns
        gap_sec = gap_ns / 1e9

        # 正常1分钟K线间隔约60秒，容忍90秒
        # 跨交易时段（午休、夜盘）的跳跃应该忽略
        dt_prev = bars[i-1].ts_dt
        dt_curr = bars[i].ts_dt

        # 如果前一个K线是交易时段结束附近，跳过
        hour_prev = dt_prev.hour + dt_prev.minute / 60.0
        hour_curr = dt_curr.hour + dt_curr.minute / 60.0

        # 午休 11:30-13:30 -> 120分钟跳过
        if 11.5 <= hour_prev <= 12.0 and 13.0 <= hour_curr <= 14.0:
            continue
        # 日盘结束 -> 夜盘开始 15:00-21:00 -> 360分钟跳过
        if 14.5 <= hour_prev <= 15.5 and 20.5 <= hour_curr <= 21.5:
            continue
        # 夜盘结束 -> 次日日盘 23:00-09:00 -> 10小时跳过
        if hour_prev >= 22.0 or hour_curr <= 9.5:
            continue

        # 周末跳过
        if dt_prev.weekday() != dt_curr.weekday() or dt_prev.weekday() >= 5:
            continue

        if gap_sec > max_gap_seconds:
            gap_count += 1
            max_gap = max(max_gap, gap_sec)

    return gap_count, max_gap


def check_outliers(bars: list[MarketBar], max_change_pct: float = 0.1) -> int:
    """检查异常价格跃变"""
    count = 0
    for i in range(1, len(bars)):
        prev_close = float(bars[i-1].close)
        curr_open = float(bars[i].open)
        if prev_close > 0:
            change = abs(curr_open - prev_close) / prev_close
            if change > max_change_pct:
                count += 1
                logger.warning(
                    f"Outlier detected: {bars[i].symbol} "
                    f"close->open {prev_close:.2f}->{curr_open:.2f} "
                    f"change={change*100:.2f}%"
                )
    return count


def check_zero_volume(bars: list[MarketBar]) -> int:
    """检查零成交量（交易时段空转数据）"""
    count = 0
    for bar in bars:
        if bar.volume == 0:
            count += 1
    return count


def generate_report(bars: list[MarketBar]) -> QualityReport:
    """生成单个合约的数据质量报告"""
    config = get_config()
    qc = config.quality

    gaps, max_gap = check_gaps(bars, qc.max_gap_seconds)
    outliers = check_outliers(bars, qc.max_price_change_pct)
    zero_vol = check_zero_volume(bars)

    # 判断健康度
    is_healthy = all([
        gaps <= len(bars) * 0.01,   # 缺口不超过1%
        outliers <= 3,               # 异常值不超过3个
        zero_vol <= len(bars) * 0.05, # 零成交量不超过5%
    ])

    return QualityReport(
        symbol=bars[0].symbol if bars else "N/A",
        check_ts_ns=time.time_ns(),
        total_bars=len(bars),
        gap_count=gaps,
        max_gap_seconds=max_gap,
        outlier_count=outliers,
        zero_volume_count=zero_vol,
        is_healthy=is_healthy,
    )