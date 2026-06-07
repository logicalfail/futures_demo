# server/config.py
"""Server layer configuration."""

from __future__ import annotations
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
import yaml


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    frontend_dir: str = "./frontend/dist"
    reload: bool = False
    log_level: str = "INFO"

    @property
    def frontend_path(self) -> Path:
        p = Path(self.frontend_dir)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / self.frontend_dir
        return p.resolve()


class SchedulerConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 60
    trading_hours_only: bool = True


class StorageConfig(BaseModel):
    type: str = "sqlite"
    path: str = "./data/futures_1m.db"

    @property
    def resolved_path(self) -> str:
        p = Path(self.path)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / self.path
        return str(p.resolve())


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def load_config(path: Optional[str] = None) -> AppConfig:
    cfg_path = path or (Path(__file__).parent.parent / "server_config.yaml")
    p = Path(cfg_path)
    if not p.exists():
        return AppConfig()
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig(**raw)
