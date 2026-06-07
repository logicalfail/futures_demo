# futures_demo/config.py
"""
配置加载器
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass
class SymbolConfig:
    symbols: list[str]
    exchange_map: dict[str, str]


@dataclass
class SourceConfig:
    name: str
    freq: str
    lookback_days: int


@dataclass
class StorageConfig:
    type: str
    path: str

    def __post_init__(self):
        """将相对路径转为绝对路径（基于配置文件所在目录）"""
        if not Path(self.path).is_absolute():
            cfg_dir = Path(__file__).parent
            self.path = (cfg_dir / self.path).resolve()


@dataclass
class SchedulerConfig:
    interval_seconds: int
    trading_hours_only: bool
    sessions: list[str]


@dataclass
class QualityConfig:
    max_gap_seconds: int
    max_price_change_pct: float
    min_volume: int


@dataclass
class AppConfig:
    symbols: SymbolConfig
    source: SourceConfig
    storage: StorageConfig
    scheduler: SchedulerConfig
    quality: QualityConfig


_config: AppConfig | None = None


def load_config(path: str = "config.yaml") -> AppConfig:
    global _config
    if _config is not None:
        return _config

    cfg_path = Path(path)
    if not cfg_path.exists():
        # 尝试相对路径
        cfg_path = Path(__file__).parent / path
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    _config = AppConfig(
        symbols=SymbolConfig(
            symbols=raw["symbols"],
            exchange_map=raw.get("exchange_map", {}),
        ),
        source=SourceConfig(**raw["source"]),
        storage=StorageConfig(**raw["storage"]),
        scheduler=SchedulerConfig(**raw["scheduler"]),
        quality=QualityConfig(**raw["quality"]),
    )
    return _config


def get_config() -> AppConfig:
    if _config is None:
        return load_config()
    return _config