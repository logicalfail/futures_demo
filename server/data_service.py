# server/data_service.py
"""
数据服务层
- 封装 futures_demo 数据层
- 查询 + 缓存 + 最新K线提取
- 品种列表管理
"""

from __future__ import annotations
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

# 确保项目根路径可导入（用于直接运行和测试）
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from futures_demo.fetcher import fetch_minute_bars, parse_symbol, get_exchange, is_trading_time as _is_trading_time
from futures_demo.storage import create_storage, StorageBackend
from futures_demo.models import MarketBar, Exchange
from futures_demo.config import load_config as load_data_config
from futures_demo import config as data_config_module  # for _config access
from futures_demo.quality import generate_report

from server.config import AppConfig


# ── 在非交易时间跳过 ──────────────────────────────────────────
# is_trading_time() 由 futures_demo.fetcher 统一管理
def is_trading_time() -> bool:
    """检查当前是否在交易时段内（委托至 fetcher 的统一实现）"""
    return _is_trading_time()


def full_symbol(symbol: str) -> str:
    """从短代码补全为完整symbol：AU2608 → AU2608.SHFE"""
    if "." in symbol:
        return symbol
    try:
        variety, _ = parse_symbol(symbol)
        exchange = get_exchange(variety)
        return f"{symbol}.{exchange.value}"
    except Exception:
        return symbol


class DataService:
    """数据服务：查询 + 缓存 + 轮询"""

    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        # 加载数据层配置
        data_cfg_path = Path(__file__).parent.parent / "config.yaml"
        self.data_config = load_data_config(str(data_cfg_path) if data_cfg_path.exists() else "")
        self._symbols_cache: list[str] = []
        self._last_poll_ts: Optional[int] = None
        self._storage: Optional[StorageBackend] = None
        self._executor = ThreadPoolExecutor(max_workers=2)

    @property
    def storage(self) -> StorageBackend:
        if self._storage is None:
            from futures_demo.config import StorageConfig as DataStorageConfig
            # 透传 server config 的 storage 路径到数据层
            sc = DataStorageConfig(
                type=self.app_config.storage.type,
                path=self.app_config.storage.resolved_path,  # 已经是绝对路径
            )
            self._storage = create_storage(sc)
        return self._storage

    def get_symbols(self) -> list[dict]:
        """
        返回品种列表，包含完整symbol和市场信息
        [{code, exchange, full_symbol, display_name}, ...]
        """
        # 从模块级的 _config (lazy loaded) 获取品种列表
        symbols_cfg = getattr(data_config_module, '_config', None)
        symbols = symbols_cfg.symbols.symbols if symbols_cfg else []
        result = []
        for sym in symbols:
            try:
                variety, contract = parse_symbol(sym)
                ex = get_exchange(variety)
                result.append({
                    "code": sym,
                    "variety": variety,
                    "exchange": ex.value,
                    "full_symbol": f"{sym}.{ex.value}",
                    "display_name": f"{sym} ({ex.value})",
                    "contract_month": contract,
                })
            except Exception:
                continue
        self._symbols_cache = [r["full_symbol"] for r in result]
        return result

    def get_symbol_codes(self) -> list[str]:
        """获取品种代码列表（不含交易所）"""
        if not self._symbols_cache:
            self.get_symbols()
        return self._symbols_cache

    def get_kline(self, symbol: str, limit: int = 1000, days_back: int = 20) -> list[dict]:
        """获取历史 K 线数据"""
        fsym = full_symbol(symbol)
        now_ns = time.time_ns()
        start_ns = now_ns - days_back * 24 * 3600 * int(1e9)
        try:
            bars = self.storage.query_bars(fsym, start_ns, now_ns, limit)
            return [self._bar_to_dict(b) for b in bars]
        except Exception as e:
            logger.error(f"Query kline failed for {fsym}: {e}")
            return []

    def get_latest_bars(self, symbol: str, n: int = 5) -> list[dict]:
        """获取最近 n 根 K线"""
        fsym = full_symbol(symbol)
        try:
            now_ns = time.time_ns()
            # 用一个宽泛的上界确保不遗漏数据（AKShare 时间戳可能略有偏移）
            end_ns = now_ns + 86400 * int(1e9)  # now + 24h
            # 尝试多个时间窗口：1h → 2d → 7d
            for window_hours in [1, 48, 168]:
                start_ns = now_ns - window_hours * 3600 * int(1e9)
                bars = self.storage.query_bars(fsym, start_ns, end_ns, n)
                if bars:
                    bars.sort(key=lambda x: x.ts_ns, reverse=True)
                    return [self._bar_to_dict(b) for b in bars[:n]]
            return []
        except Exception as e:
            logger.error(f"Get latest bars failed: {e}")
            return []

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        """获取最新报价摘要（最后一条K线的close）"""
        bars = self.get_latest_bars(symbol, 1)
        if bars:
            return bars[0]
        return None

    def get_quality_report(self) -> list[dict]:
        """获取所有品种的数据质量报告"""
        symbols = self.get_symbol_codes()
        reports = []
        now_ns = time.time_ns()
        start_ns = now_ns - 7 * 24 * 3600 * int(1e9)

        for sym in symbols:
            try:
                bars = self.storage.query_bars(sym, start_ns, now_ns, 5000)
                if not bars:
                    continue
                rpt = generate_report(bars)
                reports.append({
                    "symbol": rpt.symbol,
                    "total_bars": rpt.total_bars,
                    "gaps": rpt.gap_count,
                    "max_gap_seconds": rpt.max_gap_seconds,
                    "outliers": rpt.outlier_count,
                    "zero_volume": rpt.zero_volume_count,
                    "is_healthy": rpt.is_healthy,
                })
            except Exception:
                continue
        return reports

    def get_last_update_ts(self) -> Optional[int]:
        """获取所有品种中最近的数据时间戳"""
        symbols = self.get_symbol_codes()
        latest = 0
        for sym in symbols:
            try:
                ts = self.storage.get_latest_ts(sym)
                if ts and ts > latest:
                    latest = ts
            except Exception:
                continue
        return latest if latest > 0 else None

    def poll_new_data(self, trading_hours_only: bool = True) -> dict[str, list[dict]]:
        """
        轮询所有品种的最新数据
        - 仅在交易时段工作（可配置）
        - trading_hours_only=False 时绕过交易时段检查（手动刷新用）
        - 返回 {symbol: [new_bars_dict]}
        """
        if trading_hours_only and not is_trading_time():
            logger.debug("Outside trading hours, skipping poll")
            return {}

        # 如果 caller 明确说 trading_hours_only=False（手动刷新），
        # 传递给 fetcher 的 force=True 以绕过底层时间检查
        force_fetch = not trading_hours_only

        symbols = self.get_symbol_codes()
        logger.info(f"Polling {len(symbols)} symbols...")

        results: dict[str, list[dict]] = {}

        for sym in symbols:
            try:
                # 从 symbol 提取短代码
                code = sym.split(".")[0]

                # 获取数据库中该品种的最新时间戳
                latest_ts = self.storage.get_latest_ts(sym)

                # 拉取最近1天数据
                bars = fetch_minute_bars(code, lookback_days=1, force=force_fetch)

                if not bars:
                    continue

                # 去重：只保留数据库中不存在的K线
                new_bars: list[MarketBar] = []
                for bar in bars:
                    if latest_ts is None or bar.ts_ns > latest_ts:
                        new_bars.append(bar)

                if not new_bars:
                    continue

                # 写入存储
                self.storage.upsert_bars(new_bars)
                results[sym] = [self._bar_to_dict(b) for b in new_bars]
                logger.debug(f"  {sym}: {len(new_bars)} new bars")

            except Exception as e:
                logger.warning(f"Poll failed for {sym}: {e}")

        self._last_poll_ts = time.time_ns()
        logger.info(f"Poll complete: {len(results)} symbols with new data")
        return results

    def refresh_all(self) -> int:
        """强制刷新所有品种，返回拉取总条数（跳过交易时段检查）"""
        symbols = self.get_symbol_codes()
        total = 0

        for sym in symbols:
            try:
                code = sym.split(".")[0]
                bars = fetch_minute_bars(code, lookback_days=20, force=True)
                if bars:
                    n = self.storage.upsert_bars(bars)
                    total += n
                    logger.info(f"  {sym}: refreshed {len(bars)} bars")
            except Exception as e:
                logger.warning(f"Refresh failed for {sym}: {e}")

        self._last_poll_ts = time.time_ns()
        logger.info(f"Refresh complete: {total} total bars")
        return total

    def server_status(self) -> dict:
        """服务状态汇总"""
        last_update = self.get_last_update_ts()
        return {
            "status": "running",
            "symbols_count": len(self.get_symbol_codes()),
            "last_poll_ts": self._last_poll_ts,
            "last_update_ts": last_update,
            "last_update_str": (
                datetime.fromtimestamp(last_update / 1e9).strftime("%H:%M:%S")
                if last_update else "never"
            ),
            "is_trading_time": is_trading_time(),
            "data_dir": str(self.storage.db_path) if hasattr(self.storage, 'db_path') else "N/A",
        }

    def close(self):
        self.storage.close()
        self._executor.shutdown(wait=False)

    @staticmethod
    def _bar_to_dict(bar: MarketBar) -> dict:
        return {
            "ts_ns": bar.ts_ns,
            "ts": bar.ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": bar.volume,
            "turnover": float(bar.turnover),
            "open_interest": bar.open_interest,
            "source": bar.source.value,
        }
