# futures_demo/models.py
"""
统一行情数据模型
- MarketBar: 分钟K线（存储主体）
- MarketTick: 快照行情（扩展用，akshare分钟接口无Tick）
"""

from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, computed_field
import re


class Exchange(str, Enum):
    SHFE = "SHFE"   # 上海期货交易所
    DCE = "DCE"     # 大连商品交易所
    CZCE = "CZCE"   # 郑州商品交易所
    CFFEX = "CFFEX" # 中国金融期货交易所
    INE = "INE"     # 上海国际能源交易所


class DataSource(str, Enum):
    AKSHARE_SINA = "akshare_sina"
    AKSHARE_EASTMONEY = "akshare_eastmoney"
    CTP = "ctp"
    RQDATA = "rqdata"
    JOINQUANT = "joinquant"


class MarketBar(BaseModel):
    """
    标准化分钟K线
    - 所有价格字段统一用 Decimal 避免浮点误差
    - 时间戳统一用纳秒整数（便于排序、分区、去重）
    - symbol 格式：主力合约代码，如 RB2410.SHFE
    """
    symbol: str = Field(..., pattern=r"^[A-Z]{1,3}\d{4}\.(SHFE|DCE|CZCE|CFFEX|INE)$")
    exchange: Exchange
    ts_ns: int = Field(..., description="K线开始时间纳秒戳（东八区）")
    freq: Literal["1m", "5m", "15m", "30m", "60m", "1d"] = "1m"

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(..., ge=0, description="成交量(手)")
    turnover: Decimal = Field(..., ge=0, description="成交额(元)")
    open_interest: Optional[int] = Field(None, ge=0, description="持仓量(手)")

    source: DataSource
    source_ts_ns: Optional[int] = Field(None, description="数据源原始时间戳")
    received_ts_ns: int = Field(..., description="本地接收时间纳秒戳")

    # 计算字段（不存DB，运行时用）
    @computed_field
    @property
    def vwap(self) -> Decimal:
        """成交均价 = 成交额 / 成交量 / 合约乘数(此处不除乘数，源端已是均价)"""
        if self.volume == 0:
            return Decimal("0")
        return self.turnover / Decimal(self.volume)

    @computed_field
    @property
    def ts_dt(self) -> datetime:
        """纳秒转datetime（东八区）"""
        return datetime.fromtimestamp(self.ts_ns / 1e9)

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @field_validator("turnover", mode="before")
    @classmethod
    def _turnover_decimal(cls, v):
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    def to_dict(self) -> dict:
        """转为DB存储字典"""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange.value,
            "ts_ns": self.ts_ns,
            "freq": self.freq,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": self.volume,
            "turnover": str(self.turnover),
            "open_interest": self.open_interest,
            "source": self.source.value,
            "source_ts_ns": self.source_ts_ns,
            "received_ts_ns": self.received_ts_ns,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MarketBar":
        return cls(
            symbol=d["symbol"],
            exchange=Exchange(d["exchange"]),
            ts_ns=d["ts_ns"],
            freq=d["freq"],
            open=d["open"],
            high=d["high"],
            low=d["low"],
            close=d["close"],
            volume=d["volume"],
            turnover=d["turnover"],
            open_interest=d.get("open_interest"),
            source=DataSource(d["source"]),
            source_ts_ns=d.get("source_ts_ns"),
            received_ts_ns=d["received_ts_ns"],
        )


class QualityReport(BaseModel):
    """数据质量报告"""
    symbol: str
    check_ts_ns: int
    total_bars: int
    gap_count: int = 0
    max_gap_seconds: float = 0.0
    outlier_count: int = 0
    zero_volume_count: int = 0
    missing_sessions: list[str] = []
    is_healthy: bool = True


# 合约乘数映射（计算名义金额用）
CONTRACT_MULTIPLIER = {
    # 上期所
    "CU": 5, "AL": 5, "ZN": 5, "PB": 5, "NI": 1, "SN": 1,
    "RB": 10, "WR": 10, "HC": 10, "FU": 10, "BU": 10, "RU": 10,
    "AU": 1000, "AG": 15, "SS": 5, "SP": 5,
    # 大商所
    "A": 10, "M": 10, "Y": 10, "P": 10, "C": 10, "CS": 10,
    "J": 100, "JM": 60, "I": 100, "FB": 500, "BB": 500, "PP": 5,
    "V": 5, "EG": 10, "EB": 5, "PG": 10, "LH": 16,
    # 郑商所
    "SR": 10, "CF": 5, "TA": 5, "MA": 10, "RM": 10, "OI": 10,
    "FG": 20, "RS": 10, "LR": 20, "WH": 20, "PM": 50, "RI": 20,
    "JR": 20, "SF": 5, "SM": 5, "AP": 10, "CY": 5, "CJ": 5,
    "UR": 20, "SA": 20, "PF": 5, "PK": 5,
    # 中金所
    "IF": 300, "IH": 300, "IC": 200, "IM": 200,
    "TS": 10000, "TF": 10000, "T": 10000, "TL": 10000,
    # 能源中心
    "SC": 1000, "NR": 10, "BC": 100, "LU": 10,
}


def get_multiplier(symbol: str) -> int:
    """从symbol提取品种代码获取乘数"""
    # RB2410.SHFE -> RB
    match = re.match(r"^([A-Z]{1,3})\d{4}\.", symbol)
    if match:
        return CONTRACT_MULTIPLIER.get(match.group(1), 1)
    return 1