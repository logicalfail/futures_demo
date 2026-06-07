# futures_demo/storage.py
"""
存储层抽象
- SQLite: 开发/演示用，零配置
- TimescaleDB: 生产用，自动分区、压缩、连续聚合
统一接口：upsert_bars, query_bars, get_latest_ts, health_check
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Generator, Optional
import sqlite3
import time

from loguru import logger

from .models import MarketBar, Exchange, DataSource
from .config import get_config, StorageConfig


class StorageBackend(ABC):
    @abstractmethod
    def init_db(self) -> None: ...

    @abstractmethod
    def upsert_bars(self, bars: list[MarketBar]) -> int: ...

    @abstractmethod
    def query_bars(
        self,
        symbol: str,
        start_ns: int,
        end_ns: int,
        limit: int = 10000,
    ) -> list[MarketBar]: ...

    @abstractmethod
    def get_latest_ts(self, symbol: str) -> Optional[int]: ...

    @abstractmethod
    def get_symbols(self) -> list[str]: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...


# ==================== SQLite 实现（Demo） ====================
class SQLiteStorage(StorageBackend):
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        # 如果是相对路径，基于当前工作目录
        if not self.db_path.is_absolute():
            self.db_path = Path.cwd() / self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self.init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,  # 自动提交
            )
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA cache_size=-32768;")  # 32MB
        return self._conn

    def init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS bars_1m (
            symbol      TEXT NOT NULL,
            exchange    TEXT NOT NULL,
            ts_ns       INTEGER NOT NULL,
            freq        TEXT NOT NULL DEFAULT '1m',
            open        TEXT NOT NULL,
            high        TEXT NOT NULL,
            low         TEXT NOT NULL,
            close       TEXT NOT NULL,
            volume      INTEGER NOT NULL,
            turnover    TEXT NOT NULL,
            open_interest INTEGER,
            source      TEXT NOT NULL,
            source_ts_ns INTEGER,
            received_ts_ns INTEGER NOT NULL,
            PRIMARY KEY (symbol, ts_ns)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts ON bars_1m(symbol, ts_ns DESC);
        CREATE INDEX IF NOT EXISTS idx_bars_received ON bars_1m(received_ts_ns);
        """)
        logger.info(f"SQLite DB initialized at {self.db_path}")

    def upsert_bars(self, bars: list[MarketBar]) -> int:
        if not bars:
            return 0
        conn = self._get_conn()
        sql = """
        INSERT INTO bars_1m (
            symbol, exchange, ts_ns, freq,
            open, high, low, close,
            volume, turnover, open_interest,
            source, source_ts_ns, received_ts_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, ts_ns) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
            volume=excluded.volume, turnover=excluded.turnover, open_interest=excluded.open_interest,
            source=excluded.source, source_ts_ns=excluded.source_ts_ns, received_ts_ns=excluded.received_ts_ns
        """
        data = [
            (
                b.symbol, b.exchange.value, b.ts_ns, b.freq,
                str(b.open), str(b.high), str(b.low), str(b.close),
                b.volume, str(b.turnover), b.open_interest,
                b.source.value, b.source_ts_ns, b.received_ts_ns,
            )
            for b in bars
        ]
        cur = conn.executemany(sql, data)
        return cur.rowcount

    def query_bars(
        self,
        symbol: str,
        start_ns: int,
        end_ns: int,
        limit: int = 10000,
    ) -> list[MarketBar]:
        conn = self._get_conn()
        sql = """
        SELECT symbol, exchange, ts_ns, freq,
               open, high, low, close,
               volume, turnover, open_interest,
               source, source_ts_ns, received_ts_ns
        FROM bars_1m
        WHERE symbol = ? AND ts_ns >= ? AND ts_ns <= ?
        ORDER BY ts_ns ASC
        LIMIT ?
        """
        cur = conn.execute(sql, (symbol, start_ns, end_ns, limit))
        rows = cur.fetchall()
        return [self._row_to_bar(r) for r in rows]

    def get_latest_ts(self, symbol: str) -> Optional[int]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT MAX(ts_ns) FROM bars_1m WHERE symbol = ?", (symbol,)
        )
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None

    def get_symbols(self) -> list[str]:
        conn = self._get_conn()
        cur = conn.execute("SELECT DISTINCT symbol FROM bars_1m ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]

    def health_check(self) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_bar(row: tuple) -> MarketBar:
        return MarketBar(
            symbol=row[0],
            exchange=Exchange(row[1]),
            ts_ns=row[2],
            freq=row[3],
            open=Decimal(row[4]),
            high=Decimal(row[5]),
            low=Decimal(row[6]),
            close=Decimal(row[7]),
            volume=row[8],
            turnover=Decimal(row[9]),
            open_interest=row[10],
            source=DataSource(row[11]),
            source_ts_ns=row[12],
            received_ts_ns=row[13],
        )


# ==================== TimescaleDB 实现（生产） ====================
class TimescaleStorage(StorageBackend):
    """
    TimescaleDB 实现（需要安装 psycopg2）
    表结构利用 hypertable 自动分区、压缩、连续聚合
    """
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool = None
        self.init_db()

    def _get_conn(self):
        if self._pool is None:
            import psycopg2.pool
            self._pool = psycopg2.pool.SimpleConnectionPool(1, 10, self.dsn)
        return self._pool.getconn()

    def _put_conn(self, conn):
        if self._pool and conn:
            self._pool.putconn(conn)

    @contextmanager
    def _conn_ctx(self):
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def init_db(self) -> None:
        with self._conn_ctx() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                CREATE EXTENSION IF NOT EXISTS timescaledb;
                CREATE TABLE IF NOT EXISTS bars_1m (
                    symbol          TEXT NOT NULL,
                    exchange        TEXT NOT NULL,
                    ts_ns           BIGINT NOT NULL,
                    freq            TEXT NOT NULL DEFAULT '1m',
                    open            NUMERIC(20, 8) NOT NULL,
                    high            NUMERIC(20, 8) NOT NULL,
                    low             NUMERIC(20, 8) NOT NULL,
                    close           NUMERIC(20, 8) NOT NULL,
                    volume          BIGINT NOT NULL,
                    turnover        NUMERIC(24, 8) NOT NULL,
                    open_interest   BIGINT,
                    source          TEXT NOT NULL,
                    source_ts_ns    BIGINT,
                    received_ts_ns  BIGINT NOT NULL,
                    PRIMARY KEY (symbol, ts_ns)
                );
                SELECT create_hypertable('bars_1m', 'ts_ns',
                    chunk_time_interval => 86400000000000,  -- 1天纳秒
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
                -- 开启压缩（7天后压缩）
                ALTER TABLE bars_1m SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'symbol'
                );
                SELECT add_compression_policy('bars_1m', INTERVAL '7 days', if_not_exists => TRUE);
                -- 连续聚合：自动生成 5m/15m/1h/1d
                CREATE MATERIALIZED VIEW IF NOT EXISTS bars_5m
                WITH (timescaledb.continuous) AS
                SELECT symbol, exchange, time_bucket('5 min', to_timestamp(ts_ns/1e9)) AS bucket,
                       FIRST(open, ts_ns) AS open, MAX(high) AS high, MIN(low) AS low,
                       LAST(close, ts_ns) AS close, SUM(volume) AS volume,
                       SUM(turnover) AS turnover, LAST(open_interest, ts_ns) AS open_interest,
                       'continuous' AS source, MAX(ts_ns) AS ts_ns
                FROM bars_1m GROUP BY symbol, exchange, bucket
                WITH NO DATA;
                SELECT add_continuous_aggregate_policy('bars_5m', INTERVAL '1 hour', INTERVAL '5 min', if_not_exists => TRUE);
                """)
        logger.info("TimescaleDB initialized with hypertable + compression + continuous aggregates")

    def upsert_bars(self, bars: list[MarketBar]) -> int:
        if not bars:
            return 0
        with self._conn_ctx() as conn:
            with conn.cursor() as cur:
                sql = """
                INSERT INTO bars_1m (
                    symbol, exchange, ts_ns, freq,
                    open, high, low, close,
                    volume, turnover, open_interest,
                    source, source_ts_ns, received_ts_ns
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, ts_ns) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,
                    volume=EXCLUDED.volume, turnover=EXCLUDED.turnover, open_interest=EXCLUDED.open_interest,
                    source=EXCLUDED.source, source_ts_ns=EXCLUDED.source_ts_ns, received_ts_ns=EXCLUDED.received_ts_ns
                """
                data = [
                    (
                        b.symbol, b.exchange.value, b.ts_ns, b.freq,
                        str(b.open), str(b.high), str(b.low), str(b.close),
                        b.volume, str(b.turnover), b.open_interest,
                        b.source.value, b.source_ts_ns, b.received_ts_ns,
                    )
                    for b in bars
                ]
                cur.executemany(sql, data)
                return cur.rowcount

    def query_bars(self, symbol: str, start_ns: int, end_ns: int, limit: int = 10000) -> list[MarketBar]:
        with self._conn_ctx() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                SELECT symbol, exchange, ts_ns, freq,
                       open, high, low, close,
                       volume, turnover, open_interest,
                       source, source_ts_ns, received_ts_ns
                FROM bars_1m
                WHERE symbol = %s AND ts_ns >= %s AND ts_ns <= %s
                ORDER BY ts_ns ASC LIMIT %s
                """, (symbol, start_ns, end_ns, limit))
                rows = cur.fetchall()
                return [self._row_to_bar(r) for r in rows]

    def get_latest_ts(self, symbol: str) -> Optional[int]:
        with self._conn_ctx() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(ts_ns) FROM bars_1m WHERE symbol = %s", (symbol,))
                row = cur.fetchone()
                return row[0] if row and row[0] is not None else None

    def get_symbols(self) -> list[str]:
        with self._conn_ctx() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT symbol FROM bars_1m ORDER BY symbol")
                return [r[0] for r in cur.fetchall()]

    def health_check(self) -> bool:
        try:
            with self._conn_ctx() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()
            self._pool = None

    @staticmethod
    def _row_to_bar(row: tuple) -> MarketBar:
        return MarketBar(
            symbol=row[0],
            exchange=Exchange(row[1]),
            ts_ns=row[2],
            freq=row[3],
            open=Decimal(str(row[4])),
            high=Decimal(str(row[5])),
            low=Decimal(str(row[6])),
            close=Decimal(str(row[7])),
            volume=row[8],
            turnover=Decimal(str(row[9])),
            open_interest=row[10],
            source=DataSource(row[11]),
            source_ts_ns=row[12],
            received_ts_ns=row[13],
        )


# ==================== 工厂函数 ====================
def create_storage(cfg: StorageConfig | None = None) -> StorageBackend:
    cfg = cfg or get_config().storage
    if cfg.type == "sqlite":
        return SQLiteStorage(cfg.path)
    elif cfg.type == "timescaledb":
        return TimescaleStorage(cfg.path)  # path 这里当 dsn 用
    else:
        raise ValueError(f"Unknown storage type: {cfg.type}")