"""
API v1 — 交易策略模块数据接口

设计目标：
- 为策略引擎提供干净、可聚合的 K线数据
- 支持 source=live 直接从 AKShare 拉取（不命中缓存）
- 支持多周期聚合（服务端完成）
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger

from server.aggregation import aggregate_bars, Period
from server.data_service import full_symbol
from server.dominant import query_dominant_raw_bars, resolve_dominant_symbol, infer_dominant_contract
from futures_demo.fetcher import fetch_minute_bars, get_exchange, parse_symbol

router = APIRouter(prefix="/api/v1")


# ── 依赖注入 ───────────────────────────────────────────────────

def _get_ds(request: Request):
    """从 app.state 获取 DataService 实例"""
    return request.app.state.ds


# ── GET /api/v1/bars/{symbol} ──────────────────────────────────

@router.get("/bars/{symbol}")
async def get_bars(
    symbol: str,
    period: Period = "1m",
    start: Optional[str] = None,       # ISO8601: "2026-06-01" or "2026-06-01T09:00:00"
    end: Optional[str] = None,         # ISO8601
    limit: int = Query(500, ge=1, le=10000),
    source: Literal["auto", "db", "live"] = "auto",
    ds=Depends(_get_ds),
):
    """
    获取K线数据（支持多周期聚合 + 多数据源）

    - period: 1m, 5m, 15m, 1h, 1d
    - start/end: ISO8601 格式
    - source: auto=缓存优先, db=只查DB, live=直接从AKShare拉
    """
    # 解析时间范围
    now = datetime.now()
    start_dt = _parse_dt(start, now - timedelta(days=20))
    end_dt = _parse_dt(end, now)

    # 如果 start > end，交换
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    start_ns = int(start_dt.timestamp() * 1e9)
    end_ns = int(end_dt.timestamp() * 1e9)

    # 策略决定从哪获取数据
    raw_bars: list[dict] = []

    if source == "live":
        # 从 AKShare 拉取 → 自动写入 DB 缓存
        logger.info(f"[v1] source=live: fetching {symbol}")
        raw_bars = _fetch_and_store_live_bars(symbol, start_ns, end_ns, ds.storage)
    elif source == "db":
        # 只查 DB（扩大 days_back 确保覆盖 start）
        days_back = max(90, int((datetime.now() - start_dt).days) + 2)
        raw_bars = ds.get_kline(symbol, limit=10000, days_back=days_back)
        raw_bars = _filter_by_ns(raw_bars, start_ns, end_ns)
    else:  # auto
        # DB 优先，不够再从 AKShare 补
        days_back = max(90, int((datetime.now() - start_dt).days) + 2)
        raw_bars = ds.get_kline(symbol, limit=10000, days_back=days_back)
        raw_bars = _filter_by_ns(raw_bars, start_ns, end_ns)
        bars_count = len(raw_bars)
        # 如果DB数据为空或明显缺失，尝试 AKShare 直拉（含自动写库）
        if bars_count == 0:
            logger.info(f"[v1] source=auto: DB empty for {symbol}, falling back to live")
            raw_bars = _fetch_and_store_live_bars(symbol, start_ns, end_ns, ds.storage)
        else:
            logger.info(f"[v1] source=auto: returning {bars_count} bars from DB")

    # 聚合
    result = aggregate_bars(raw_bars, period)

    # 截断
    if len(result) > limit:
        result = result[-limit:]

    return {
        "symbol": full_symbol(symbol),
        "period": period,
        "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(result),
        "source": source,
        "bars": _clean_bars(result),
    }


# ── GET /api/v1/quotes ────────────────────────────────────────

@router.get("/quotes/{symbol}")
async def get_quote(symbol: str, ds=Depends(_get_ds)):
    """获取品种最新报价"""
    quote = ds.get_latest_quote(symbol)
    return {"symbol": symbol, "quote": quote}


@router.get("/quotes")
async def get_quotes(
    symbols: str = Query("", description="逗号分隔的品种列表，空=全部"),
    ds=Depends(_get_ds),
):
    """获取批量最新报价"""
    if symbols:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        sym_list = ds.get_symbol_codes()
    results = {}
    for sym in sym_list:
        try:
            q = ds.get_latest_quote(sym)
            if q:
                results[sym] = q
        except Exception:
            continue
    return {"count": len(results), "quotes": results}


# ── GET /api/v1/symbols ───────────────────────────────────────

@router.get("/symbols")
async def list_symbols(ds=Depends(_get_ds)):
    """获取所有品种列表"""
    return {"symbols": ds.get_symbols()}


@router.get("/symbols/{code}")
async def symbol_meta(code: str):
    """获取品种元信息（含合约乘数、最小变动等）"""
    from futures_demo.models import get_multiplier
    try:
        variety, contract = parse_symbol(code)
    except ValueError:
        return {"error": f"Invalid symbol: {code}"}
    exchange = get_exchange(variety)
    multiplier = get_multiplier(f"{code}.{exchange.value}")
    return {
        "code": code,
        "variety": variety,
        "exchange": exchange.value,
        "full_symbol": f"{code}.{exchange.value}",
        "contract_month": contract,
        "multiplier": multiplier,
    }


# ── GET /api/v1/dominant ────────────────────────────────────────

@router.get("/dominant")
async def list_dominant_symbols(ds=Depends(_get_ds)):
    """
    获取所有品种的当前主力合约列表。

    优先通过 AKShare match_main_contract() 实时解析主力合约，
    失败时回退到 config.yaml 中该品种的静态合约。
    返回格式与 /api/symbols 兼容，前端可直接替换使用。
    """
    # 从 config 获取已有品种列表，提取唯一 variety
    symbols_info = ds.get_symbols()
    seen: set[str] = set()
    varieties: list[str] = []
    # 构建 variety → config 合约的 fallback 映射
    fallback_map: dict[str, dict] = {}
    for s in symbols_info:
        v = s.get("variety", "")
        if v and v not in seen:
            seen.add(v)
            varieties.append(v)
            fallback_map[v] = s  # 保存第一个 config 合约作为 fallback

    logger.info(f"[v1] Resolving dominant for {len(varieties)} varieties...")

    result: list[dict] = []
    akshare_count = 0
    inferred_count = 0
    config_count = 0

    for variety in varieties:
        # 1) 尝试 AKShare 实时查询
        try:
            dom = resolve_dominant_symbol(variety)
        except Exception as e:
            logger.warning(f"[v1] AKShare resolve failed for {variety}: {e}")
            dom = None

        if dom is not None:
            code = dom.split(".")[0]
            exchange = dom.split(".")[1] if "." in dom else ""
            result.append({
                "code": code,
                "variety": variety,
                "exchange": exchange,
                "full_symbol": dom,
                "display_name": f"{code} ({exchange})",
                "contract_month": code[len(variety):] if code.startswith(variety) else "",
            })
            akshare_count += 1
            continue

        # 2) 时间推断 fallback
        try:
            dom = infer_dominant_contract(variety)
        except Exception as e:
            logger.warning(f"[v1] Time inference failed for {variety}: {e}")
            dom = None

        if dom is not None:
            code = dom.split(".")[0]
            exchange = dom.split(".")[1] if "." in dom else ""
            result.append({
                "code": code,
                "variety": variety,
                "exchange": exchange,
                "full_symbol": dom,
                "display_name": f"{code} ({exchange})",
                "contract_month": code[len(variety):] if code.startswith(variety) else "",
            })
            inferred_count += 1
            continue

        # 3) config.yaml 静态合约兜底
        fb = fallback_map.get(variety)
        if fb:
            logger.info(f"[v1] Dominant {variety} fallback to config: {fb['full_symbol']}")
            result.append(fb)
            config_count += 1
        else:
            logger.warning(f"[v1] No dominant or fallback for {variety}, skipping")

    logger.info(
        f"[v1] Dominant symbols: {akshare_count} AKShare, "
        f"{inferred_count} inferred, {config_count} config, {len(result)} total"
    )
    return {"symbols": result}


# ── GET /api/v1/dominant/{variety} ─────────────────────────────

@router.get("/dominant/{variety}")
async def get_dominant_bars(
    variety: str,
    start: Optional[str] = None,       # ISO8601
    end: Optional[str] = None,         # ISO8601
    limit: int = Query(500, ge=1, le=10000),
    rollover: Literal["none", "chain", "adjust"] = "chain",
    ds=Depends(_get_ds),
):
    """
    获取品种主力合约的分钟K线数据（自动换月适配）。

    - variety: 品种缩写，大小写不敏感，如 RB / au / V
    - rollover: 换月处理模式
        - chain (默认): 拼接历史+当前主力，标注换月点
        - adjust: 拼接 + 后向比例复权
        - none: 只返回当前主力合约数据
    - start/end: ISO8601 时间范围
    """
    now = datetime.now()
    start_dt = _parse_dt(start, now - timedelta(days=20))
    end_dt = _parse_dt(end, now)
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    start_ns = int(start_dt.timestamp() * 1e9)
    end_ns = int(end_dt.timestamp() * 1e9)

    result = query_dominant_raw_bars(
        variety=variety,
        start_ns=start_ns,
        end_ns=end_ns,
        storage=ds.storage,
        rollover_mode=rollover,
        limit=limit,
    )

    return result


# ── 辅助函数 ──────────────────────────────────────────────────

def _parse_dt(s: Optional[str], default: datetime) -> datetime:
    if not s:
        return default
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return default


def _filter_by_ns(bars: list[dict], start_ns: int, end_ns: int) -> list[dict]:
    """按纳秒时间戳范围过滤"""
    return [b for b in bars if start_ns <= b["ts_ns"] <= end_ns]


def _fetch_and_store_live_bars(
    symbol: str, start_ns: int, end_ns: int, storage,
) -> list[dict]:
    """
    从 AKShare 直拉数据 → 全量写入 DB → 返回时间范围内结果。
    下次同品种查 source=db/auto 直接命中缓存。
    """
    code = symbol.split(".")[0] if "." in symbol else symbol
    try:
        bars = fetch_minute_bars(code, lookback_days=5, force=True)
    except Exception as e:
        logger.error(f"[v1] live fetch failed: {e}")
        return []
    if not bars:
        return []

    # 全量写入 DB（upsert 自动去重）
    n = storage.upsert_bars(bars)
    logger.info(f"[v1] live: stored {n} bars for {code}")

    # 返回时间范围内的子集
    result = [
        {
            "ts_ns": b.ts_ns,
            "ts": b.ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": b.volume,
            "turnover": float(b.turnover),
            "open_interest": b.open_interest,
        }
        for b in bars
        if start_ns <= b.ts_ns <= end_ns
    ]
    logger.info(f"[v1] live: {len(bars)} total, {len(result)} in range")
    return result


def _clean_bars(bars: list[dict]) -> list[dict]:
    """移除内部字段，只保留策略需要的字段"""
    clean = []
    for b in bars:
        clean.append({
            "ts": b["ts"],
            "ts_ns": b["ts_ns"],
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "close": b["close"],
            "volume": b["volume"],
            "open_interest": b.get("open_interest"),
        })
    return clean
