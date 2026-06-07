# futures_demo/fetcher.py
"""
AKShare 分钟线获取器
- 使用新浪财经接口（akshare底层封装）
- 支持主力合约映射
- 自动处理交易时段、夜盘
"""

from __future__ import annotations
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Generator, Optional
import akshare as ak
import pandas as pd
from loguru import logger

from .models import MarketBar, Exchange, DataSource, get_multiplier
from .config import load_config


# 品种代码 -> 交易所映射（配置文件里也有，这里做兜底）
SYMBOL_EXCHANGE_MAP = {
    # SHFE
    "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE", "PB": "SHFE", "NI": "SHFE", "SN": "SHFE",
    "RB": "SHFE", "WR": "SHFE", "HC": "SHFE", "FU": "SHFE", "BU": "SHFE", "RU": "SHFE",
    "AU": "SHFE", "AG": "SHFE", "SS": "SHFE", "SP": "SHFE",
    # DCE
    "A": "DCE", "M": "DCE", "Y": "DCE", "P": "DCE", "C": "DCE", "CS": "DCE",
    "J": "DCE", "JM": "DCE", "I": "DCE", "FB": "DCE", "BB": "DCE", "PP": "DCE",
    "V": "DCE", "EG": "DCE", "EB": "DCE", "PG": "DCE", "LH": "DCE",
    # CZCE
    "SR": "CZCE", "CF": "CZCE", "TA": "CZCE", "MA": "CZCE", "RM": "CZCE", "OI": "CZCE",
    "FG": "CZCE", "RS": "CZCE", "LR": "CZCE", "WH": "CZCE", "PM": "CZCE", "RI": "CZCE",
    "JR": "CZCE", "SF": "CZCE", "SM": "CZCE", "AP": "CZCE", "CY": "CZCE", "CJ": "CZCE",
    "UR": "CZCE", "SA": "CZCE", "PF": "CZCE", "PK": "CZCE",
    # CFFEX
    "IF": "CFFEX", "IH": "CFFEX", "IC": "CFFEX", "IM": "CFFEX",
    "TS": "CFFEX", "TF": "CFFEX", "T": "CFFEX", "TL": "CFFEX",
    # INE
    "SC": "INE", "NR": "INE", "BC": "INE", "LU": "INE",
}


def parse_symbol(symbol: str) -> tuple[str, str]:
    """
    解析主力合约代码
    RB2410 -> (RB, 2410)
    """
    import re
    match = re.match(r"^([A-Z]{1,3})(\d{4})$", symbol)
    if not match:
        raise ValueError(f"Invalid symbol format: {symbol}")
    return match.group(1), match.group(2)


def get_exchange(variety: str) -> Exchange:
    """获取品种对应的交易所"""
    return Exchange(SYMBOL_EXCHANGE_MAP.get(variety, "SHFE"))


def fetch_minute_bars(symbol: str, lookback_days: int = 5) -> list[MarketBar]:
    """
    获取单个品种的分钟K线
    - 使用 akshare.futures_zh_minute_sina
    - symbol 格式：RB2410, IF2008, AU2412（直接合约代码）
    - 返回标准化 MarketBar 列表
    """
    variety, contract = parse_symbol(symbol)
    exchange = get_exchange(variety)

    logger.info(f"Fetching {symbol} from akshare/sina...")

    try:
        # akshare 新浪接口，列：datetime, open, high, low, close, volume, hold
        df: pd.DataFrame = ak.futures_zh_minute_sina(symbol=symbol, period="1")
    except Exception as e:
        logger.error(f"akshare fetch failed for {symbol}: {e}")
        return []

    if df is None or df.empty:
        logger.warning(f"No data returned for {symbol}")
        return []

    # 列名标准化
    col_map = {
        "datetime": "datetime", "open": "open", "high": "high",
        "low": "low", "close": "close", "volume": "volume", "hold": "hold",
    }
    # 只取需要的列（如果存在）
    available_cols = {c.lower() for c in df.columns}
    if not {"datetime", "open", "high", "low", "close", "volume"}.issubset(available_cols):
        logger.error(f"Missing columns for {symbol}: got {list(df.columns)}")
        return []

    # 过滤回溯天数
    cutoff = datetime.now() - timedelta(days=lookback_days)
    df["dt"] = pd.to_datetime(df["datetime"])
    df = df[df["dt"] >= cutoff].copy()

    if df.empty:
        logger.warning(f"No recent data for {symbol} after cutoff")
        return []

    bars: list[MarketBar] = []
    received_ns = time.time_ns()

    for _, row in df.iterrows():
        try:
            dt = row["dt"]
            ts_ns = int(dt.timestamp() * 1e9)

            has_hold = "hold" in df.columns and pd.notna(row.get("hold"))

            bar = MarketBar(
                symbol=f"{symbol}.{exchange.value}",
                exchange=exchange,
                ts_ns=ts_ns,
                freq="1m",
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row["volume"]),
                turnover=Decimal("0"),
                open_interest=int(row["hold"]) if has_hold else None,
                source=DataSource.AKSHARE_SINA,
                source_ts_ns=ts_ns,
                received_ts_ns=received_ns,
            )
            bars.append(bar)
        except Exception as e:
            logger.warning(f"Parse row failed for {symbol}: {row}, error: {e}")
            continue

    logger.info(f"Fetched {len(bars)} bars for {symbol}")
    return bars


def fetch_all_symbols(symbols: list[str], lookback_days: int = 5) -> Generator[MarketBar, None, None]:
    """批量获取所有品种，生成器模式节省内存"""
    for sym in symbols:
        bars = fetch_minute_bars(sym, lookback_days)
        for bar in bars:
            yield bar
        # 礼貌性延迟，避免触发新浪频控
        time.sleep(0.2)


# ============ 备用数据源：东方财富（akshare封装） ============
def fetch_minute_bars_em(symbol: str, lookback_days: int = 5) -> list[MarketBar]:
    """
    备用源：东方财富分钟线
    ak.futures_zh_minute_em(symbol="RB2410", period="1")
    注意：东财接口使用直接合约代码
    """
    variety, contract = parse_symbol(symbol)
    exchange = get_exchange(variety)

    try:
        df: pd.DataFrame = ak.futures_zh_minute_em(symbol=symbol, period="1")
    except Exception as e:
        logger.error(f"EM fetch failed for {symbol}: {e}")
        return []

    if df is None or df.empty:
        return []

    # 东财列：时间, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 持仓量
    df_clean = df.copy()
    df_clean.columns = [c.strip() for c in df_clean.columns]

    # 中文列名映射
    cn_map = {
        "时间": "datetime", "开盘": "open", "最高": "high",
        "最低": "low", "收盘": "close", "成交量": "volume",
        "成交额": "turnover", "持仓量": "hold",
    }
    for old, new in cn_map.items():
        if old in df_clean.columns:
            df_clean.rename(columns={old: new}, inplace=True)

    required = {"datetime", "open", "high", "low", "close", "volume"}
    if not required.issubset(df_clean.columns):
        logger.error(f"EM missing columns for {symbol}: {list(df_clean.columns)}")
        return []

    cutoff = datetime.now() - timedelta(days=lookback_days)
    df_clean["dt"] = pd.to_datetime(df_clean["datetime"])
    df_clean = df_clean[df_clean["dt"] >= cutoff].copy()

    bars = []
    received_ns = time.time_ns()

    for _, row in df_clean.iterrows():
        try:
            dt = row["dt"]
            ts_ns = int(dt.timestamp() * 1e9)
            bar = MarketBar(
                symbol=f"{symbol}.{exchange.value}",
                exchange=exchange,
                ts_ns=ts_ns,
                freq="1m",
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row["volume"]),
                turnover=Decimal(str(row.get("turnover", 0))) if "turnover" in df_clean.columns else Decimal("0"),
                open_interest=int(row["hold"]) if "hold" in df_clean.columns and pd.notna(row["hold"]) else None,
                source=DataSource.AKSHARE_EASTMONEY,
                source_ts_ns=ts_ns,
                received_ts_ns=received_ns,
            )
            bars.append(bar)
        except Exception as e:
            logger.warning(f"EM parse failed: {e}")
            continue

    return bars