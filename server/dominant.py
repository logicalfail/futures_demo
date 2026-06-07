"""
server/dominant.py - 主力合约解析与换月拼接

核心能力：
1. resolve_dominant_symbol(variety) -> "RB2610.SHFE"
   通过 AKShare match_main_contract 实时查询当前主力合约
2. query_dominant_bars(variety, start_ns, end_ns, storage, rollover_mode)
   获取主力合约分钟K线，处理合约换月拼接

换月策略：
- chain（默认）：拼接历史+当前主力，换月处标记
- adjust：链式 + 后向比例复权
- none：只返回当前主力
"""

from __future__ import annotations
import re

import akshare as ak
from loguru import logger

from futures_demo.fetcher import (
    fetch_minute_bars,
    parse_symbol,
    SYMBOL_EXCHANGE_MAP,
)
from futures_demo.models import MarketBar
from server.data_service import full_symbol


# ── 主力合约解析 ─────────────────────────────────────────────

# 部分品种的固定换月周期（不随逐月滚动，有固定的主力月份模式）
# 格式: {variety: [month1, month2, ...]}
ROLL_CYCLE = {
    # 农产品/黑色：01→05→09→01
    "RB": [1, 5, 10],     # 螺纹钢 01→05→10
    "HC": [1, 5, 10],     # 热卷 01→05→10
    "I":  [1, 5, 9],      # 铁矿石 01→05→09
    "J":  [1, 5, 9],      # 焦炭
    "JM": [1, 5, 9],      # 焦煤
    "P":  [1, 5, 9],      # 棕榈油
    "C":  [1, 5, 9],      # 玉米
    "M":  [1, 5, 9],      # 豆粕
    "Y":  [1, 5, 9],      # 豆油
    "CF": [1, 5, 9],      # 棉花
    "SR": [1, 5, 9],      # 白糖
    # 贵金属
    "AU": [6, 12],        # 黄金 06→12
    "AG": [6, 12],        # 白银 06→12
    # 化工：多数逐月但主力集中在 01/05/09
    "V":  [1, 5, 9],      # PVC
    "PP": [1, 5, 9],      # 聚丙烯
    "L":  [1, 5, 9],      # 聚乙烯
    "MA": [1, 5, 9],      # 甲醇
    "TA": [1, 5, 9],      # PTA
    "FG": [1, 5, 9],      # 玻璃
    "SA": [1, 5, 9],      # 纯碱
    "UR": [1, 5, 9],      # 尿素
    # 有色金属：逐月，主力一般是近月
    "CU": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "AL": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "ZN": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
}

# 品种默认主力月份推断：如果不在 ROLL_CYCLE 中，使用所有12个月
DEFAULT_ROLL_MONTHS = [1, 5, 9]


def _get_variety_roll_months(variety: str) -> list[int]:
    """获取品种的主力换月月份列表"""
    return ROLL_CYCLE.get(variety.upper(), DEFAULT_ROLL_MONTHS)


def resolve_dominant_symbol(variety: str) -> str | None:
    """
    将品种缩写解析为当前主力合约完整 symbol。

    使用 AKShare match_main_contract() 获取交易所当前所有主力合约，
    从中匹配品种代码。

    返回格式: "RB2610.SHFE" 或 None（查找失败）
    """
    variety = variety.strip().upper()
    if not variety:
        return None

    # 确定交易所
    exchange_str = SYMBOL_EXCHANGE_MAP.get(variety)
    if exchange_str is None:
        logger.warning(f"Unknown variety: {variety}")
        return None

    exchange_lower = exchange_str.lower()

    # 交易所到 match_main_contract 入参的映射
    EXCHANGE_MAP = {
        "shfe": "shfe", "dce": "dce", "czce": "czce",
        "cffex": "cffex", "ine": "ine", "gfex": "gfex",
    }
    param = EXCHANGE_MAP.get(exchange_lower)
    if not param:
        return None

    try:
        raw = ak.match_main_contract(param)
    except Exception as e:
        logger.warning(f"match_main_contract({param}) failed: {e}")
        return None

    # 解析返回的逗号分隔字符串
    # 返回值格式: "FU2609,SC2607,AL2607,...,RB2610,..."
    # 可能有中文字段混入（AKShare 的 stdout 打印），过滤掉
    pattern = re.compile(r"^" + re.escape(variety) + r"\d{4}$")
    for part in raw.split(","):
        part = part.strip()
        if pattern.match(part):
            return f"{part}.{exchange_str}"

    # 如果没找到，尝试从 config 的品种列表获取
    logger.warning(f"Dominant contract not found for {variety} in {exchange_str}, fallback to config")
    return None


def resolve_dominant_symbol_from_config(variety: str) -> str | None:
    """
    从 config.yaml 的品种配置中查找匹配的合约（兜底方案）。
    用于 AKShare 查不到时的 fallback。
    """
    from futures_demo.config import get_config
    try:
        cfg = get_config()
        for sym in cfg.symbols.symbols:
            v, _ = parse_symbol(sym)
            if v == variety:
                return full_symbol(sym)
    except Exception:
        pass
    return None


# ── 换月推断 ─────────────────────────────────────────────


def _contract_year_month(contract: str) -> tuple[int, int]:
    """从合约代码提取年份和月份: 'RB2610' -> (2026, 10)"""
    m = re.match(r"^[A-Z]{1,3}(\d{4})$", contract)
    if not m:
        raise ValueError(f"Cannot parse contract: {contract}")
    ym = m.group(1)
    year = 2000 + int(ym[:2])
    month = int(ym[2:])
    return year, month


def guess_previous_dominant(variety: str, current_contract: str) -> str | None:
    """
    根据当前主力合约，推测上一个主力合约代码。

    策略：
    1. 获取品种的换月循环（如 RB: [1,5,10]）
    2. 找到当前月份在循环中的位置
    3. 取前一个元素
    4. 如果跨年则递减年份

    示例：RB2610 → RB2609 (10 的循环前一位是 09)
          如果循环是 [1,5,10]，10 的前一位是 5，但 09 不在循环中
          所以实际上可能 RB2605 → RB2610 而不是 RB2609
          这里做简单处理：减一个月，然后找到最近的循环月份
    """
    variety = variety.upper()
    try:
        _, curr_month = _contract_year_month(current_contract)
    except ValueError:
        return None

    roll_months = _get_variety_roll_months(variety)

    # 如果当前月份在循环中，找前一个循环月份
    if curr_month in roll_months:
        idx = roll_months.index(curr_month)
        if idx > 0:
            prev_month = roll_months[idx - 1]
        else:
            # 循环到年尾：前一个循环月份 + 换到上年
            prev_month = roll_months[-1]
            # 年份减1
            try:
                curr_year, _ = _contract_year_month(current_contract)
                prev_year = curr_year - 1
                # 构造新合约代码: variety + 年份后两位 + 月份
                variety_code = re.match(r"^([A-Z]{1,3})\d{4}$", current_contract).group(1)
                return f"{variety_code}{str(prev_year)[-2:]}{prev_month:02d}"
            except Exception:
                return None

        variety_code = re.match(r"^([A-Z]{1,3})\d{4}$", current_contract).group(1)
        try:
            curr_year, _ = _contract_year_month(current_contract)
            return f"{variety_code}{str(curr_year)[-2:]}{prev_month:02d}"
        except Exception:
            return None

    # 如果当前月份不在循环中（可能误匹配），减一个月试试
    prev_month = curr_month - 1 if curr_month > 1 else 12
    try:
        curr_year, _ = _contract_year_month(current_contract)
        if prev_month > curr_month:
            prev_year = curr_year - 1
        else:
            prev_year = curr_year
        variety_code = re.match(r"^([A-Z]{1,3})\d{4}$", current_contract).group(1)
        return f"{variety_code}{str(prev_year)[-2:]}{prev_month:02d}"
    except Exception:
        return None


# ── 主力合约数据查询 ─────────────────────────────────────


def query_dominant_raw_bars(
    variety: str,
    start_ns: int,
    end_ns: int,
    storage,
    rollover_mode: str = "chain",
    limit: int = 10000,
) -> dict:
    """
    获取主力合约分钟K线，含换月处理。

    参数:
        variety: 品种缩写 (大小写不敏感)
        start_ns, end_ns: 纳秒时间戳范围
        storage: StorageBackend 实例
        rollover_mode: "none" | "chain" | "adjust"
        limit: 最大返回条数

    返回:
        {
            "variety": str,
            "dominant_symbol": str,
            "rollovers": list[{"from": str, "to": str, "ts_ns": int, "ts": str}],
            "count": int,
            "bars": list[dict],
        }
    """
    variety = variety.strip().upper()
    v_code = variety  # 品种代码

    # 第1步：解析当前主力合约
    dom_symbol = resolve_dominant_symbol(v_code)
    if not dom_symbol:
        # fallback: 从 config 找
        dom_symbol = resolve_dominant_symbol_from_config(v_code)
    if not dom_symbol:
        return {
            "variety": variety,
            "dominant_symbol": None,
            "rollovers": [],
            "count": 0,
            "bars": [],
            "error": f"Cannot resolve dominant contract for {variety}",
        }

    dom_contract = dom_symbol.split(".")[0]  # "RB2610"

    # 第2步：确定要查询的合约列表
    symbols_to_query = [dom_symbol]

    if rollover_mode in ("chain", "adjust"):
        # 尝试获取前一个主力合约
        prev_contract = guess_previous_dominant(v_code, dom_contract)
        if prev_contract:
            exchange_str = SYMBOL_EXCHANGE_MAP.get(v_code)
            if exchange_str:
                prev_symbol = f"{prev_contract}.{exchange_str}"
                if prev_symbol != dom_symbol:
                    symbols_to_query.insert(0, prev_symbol)
                    logger.info(f"[dominant] Will chain: {prev_symbol} -> {dom_symbol}")

    # 第3步：从 DB 查询
    all_bars: dict[str, list[MarketBar]] = {}
    for sym in symbols_to_query:
        try:
            bars = storage.query_bars(sym, start_ns, end_ns, limit)
            if bars:
                all_bars[sym] = bars
                logger.info(f"[dominant] Found {len(bars)} bars in DB for {sym}")
        except Exception as e:
            logger.warning(f"[dominant] DB query failed for {sym}: {e}")

    # 第4步：对于没有 DB 数据且有必要拉取的合约，从 AKShare 实时拉取
    # 判断标准：如果当前主力合约的数据已覆盖查询起始时间，不需要拉历史合约
    current_has_start = False
    if dom_symbol in all_bars:
        dom_bars = all_bars[dom_symbol]
        if dom_bars:
            earliest_ts = min(b.ts_ns for b in dom_bars)
            current_has_start = earliest_ts <= start_ns + 120 * 1_000_000_000  # 容忍2分钟偏差

    for sym in symbols_to_query:
        if sym in all_bars and len(all_bars[sym]) > 0:
            continue  # 已有数据
        if sym != dom_symbol and current_has_start:
            logger.info(f"[dominant] Skip fetching {sym}: current dominant covers query window")
            continue  # 当前主力已覆盖，不需要历史合约

        code = sym.split(".")[0]
        logger.info(f"[dominant] Fetching live for {code}...")
        try:
            live_bars = fetch_minute_bars(code, lookback_days=5, force=True)
            if live_bars:
                storage.upsert_bars(live_bars)
                filtered = [b for b in live_bars if start_ns <= b.ts_ns <= end_ns]
                if filtered:
                    all_bars[sym] = filtered
                    logger.info(f"[dominant] Fetched {len(filtered)} live bars for {sym}")
        except Exception as e:
            logger.warning(f"[dominant] Live fetch failed for {code}: {e}")

    # 第5步：拼接换月 + 格式化输出
    if rollover_mode == "none" or len(all_bars) <= 1:
        # 只返回当前主力
        all_dicts, rollovers = _bars_to_dicts(all_bars.get(dom_symbol, [])), []
    else:
        all_dicts, rollovers = _chain_and_format(all_bars, dom_symbol, rollover_mode == "adjust")

    # 截断
    if len(all_dicts) > limit:
        all_dicts = all_dicts[-limit:]

    return {
        "variety": variety,
        "dominant_symbol": dom_symbol,
        "rollovers": rollovers,
        "count": len(all_dicts),
        "bars": all_dicts,
    }


def _bars_to_dicts(bars: list[MarketBar]) -> list[dict]:
    """MarketBar 列表转为 API 响应用的 dict 列表"""
    return [{
        "ts_ns": b.ts_ns,
        "ts": b.ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "open": float(b.open),
        "high": float(b.high),
        "low": float(b.low),
        "close": float(b.close),
        "volume": b.volume,
        "turnover": float(b.turnover) if b.turnover else 0,
        "open_interest": b.open_interest,
    } for b in bars]


def _chain_and_format(
    all_bars: dict[str, list[MarketBar]],
    current_symbol: str,
    adjust_price: bool,
) -> tuple[list[dict], list[dict]]:
    """
    拼接多合约数据并格式化输出。

    规则：
    1. 按时间排序
    2. 找到当前主力第一条 bar 的时间 = 换月点
    3. 换月点之前：允许历史合约数据（当前合约数据在换月点前若存在，也会被包括）
    4. 换月点及之后：只使用当前主力合约数据（防止回摆）
    5. 只记录一次换月（从上一个主力 → 当前主力）
    """
    # 按时间合并
    sorted_pairs: list[tuple[MarketBar, str]] = []
    for sym, bars in all_bars.items():
        for b in bars:
            sorted_pairs.append((b, sym))
    sorted_pairs.sort(key=lambda x: x[0].ts_ns)

    if not sorted_pairs:
        return [], []

    # 找到当前主力第一条 bar 的索引 = 换月分界点
    rollover_idx = None
    for i, (b, sym) in enumerate(sorted_pairs):
        if sym == current_symbol:
            rollover_idx = i
            break

    # 如果没有当前主力数据，全部数据都来自历史合约
    if rollover_idx is None:
        result_bars = sorted_pairs
        rollovers = []
    else:
        result_bars = []
        rollovers: list[dict] = []
        prev_sym: str | None = None
        has_rolled = False

        for i, (b, sym) in enumerate(sorted_pairs):
            # 换月点之前：所有合约都接受
            # 换月点及之后：只接受当前主力（防回摆）
            if i >= rollover_idx and sym != current_symbol:
                continue

            # 检测换月（只记录第一次有效换月）
            if not has_rolled and prev_sym is not None and sym != prev_sym:
                if sym == current_symbol:
                    rollovers.append({
                        "from": prev_sym,
                        "to": sym,
                        "ts_ns": b.ts_ns,
                        "ts": b.ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    has_rolled = True
                    logger.info(f"[dominant] Rollover: {prev_sym} -> {sym} at {b.ts_dt}")

            result_bars.append((b, sym))
            prev_sym = sym

    # 计算价格调整系数
    adj_factor: float | None = None
    if adjust_price and rollover_idx is not None:
        curr_bar = result_bars[rollover_idx][0] if rollover_idx < len(result_bars) else None
        if curr_bar:
            ref_price = float(curr_bar.open)
            # 找到换月点附近的历史合约 bar 作为调整基准
            best_bar = None
            best_diff = float("inf")
            for b, sym in result_bars:
                if sym != current_symbol:
                    diff = abs(b.ts_ns - curr_bar.ts_ns)
                    if diff < best_diff:
                        best_diff = diff
                        best_bar = b
            if best_bar and ref_price > 0:
                old_price = float(best_bar.close)
                if old_price > 0:
                    adj_factor = ref_price / old_price
                    logger.info(f"[dominant] Price adjustment factor: {adj_factor:.4f}")

    # 格式化输出
    result: list[dict] = []
    for b, sym in result_bars:
        d = {
            "ts_ns": b.ts_ns,
            "ts": b.ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": b.volume,
            "turnover": float(b.turnover) if b.turnover else 0,
            "open_interest": b.open_interest,
        }

        if adjust_price and adj_factor is not None and adj_factor != 1.0 and sym != current_symbol:
            d["open"] = round(d["open"] * adj_factor, 2)
            d["high"] = round(d["high"] * adj_factor, 2)
            d["low"] = round(d["low"] * adj_factor, 2)
            d["close"] = round(d["close"] * adj_factor, 2)

        result.append(d)

    return result, rollovers


def _chain_rollover(
    all_bars: dict[str, list[MarketBar]],
    current_symbol: str,
    adjust_price: bool = False,
) -> tuple[list[MarketBar], list[dict]]:
    """
    拼接多个合约的 K 线数据，处理换月。

    策略：
    1. 按时间排序所有 bar
    2. 检测换月点：当连续两条 bar 属于不同合约时
    3. adjust=True 时，以当前主力为基准，历史合约价格做比例调整
    4. 返回拼接后的 bars + rollover 标注
    """
    # 按品种分组排序
    sorted_bars: list[tuple[MarketBar, str]] = []
    for sym, bars in all_bars.items():
        for b in bars:
            sorted_bars.append((b, sym))

    # 按时间排序
    sorted_bars.sort(key=lambda x: x[0].ts_ns)

    if not sorted_bars:
        return [], []

    # 检测换月点 + 拼接
    chained: list[MarketBar] = []
    rollovers: list[dict] = []
    prev_sym: str | None = None

    # 计算价格调整系数
    adjustment_factor: float | None = None
    # 找到第一个当前主力合约的 bar 作为基准
    current_first_bar = None
    for b, sym in sorted_bars:
        if sym == current_symbol:
            current_first_bar = b
            break

    for b, sym in sorted_bars:
        if prev_sym is not None and sym != prev_sym:
            # 换月点
            rollovers.append({
                "from": prev_sym,
                "to": sym,
                "ts_ns": b.ts_ns,
                "ts": b.ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
            })
            logger.info(f"[dominant] Rollover: {prev_sym} -> {sym} at {b.ts_dt}")

            if adjust_price and adjustment_factor is not None and sym == current_symbol:
                # 换到当前主力，重置调整系数
                adjustment_factor = None

        # 如果开启了价格调整，且当前 bar 是历史合约
        if adjust_price and sym != current_symbol:
            if adjustment_factor is None and current_first_bar is not None:
                # 计算调整系数：用当前主力第一个 bar 的开盘价 / 历史合约同时间附近的价格
                # 简单做法：找到时间最接近的 bar，用 close 比例
                closest_bar = None
                closest_diff = float("inf")
                for hb, hs in sorted_bars:
                    if hs == current_symbol:
                        diff = abs(hb.ts_ns - current_first_bar.ts_ns)
                        if diff < closest_diff:
                            closest_diff = diff
                            closest_bar = hb
                if closest_bar and closest_bar.ts_ns != 0:
                    # 调整系数 = 当前主力价格 / 历史合约价格
                    ref_price = float(closest_bar.close)
                    cur_price = float(current_first_bar.close)
                    if ref_price > 0:
                        adjustment_factor = cur_price / ref_price

            if adjustment_factor is not None and adjustment_factor != 1.0:
                # 应用调整
                b.open = round(b.open * adjustment_factor, 2)
                b.high = round(b.high * adjustment_factor, 2)
                b.low = round(b.low * adjustment_factor, 2)
                b.close = round(b.close * adjustment_factor, 2)

        chained.append(b)
        prev_sym = sym

    return chained, rollovers
