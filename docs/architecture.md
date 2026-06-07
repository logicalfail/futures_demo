# Futures Terminal — Architecture Design

> 为交易策略模块、下单模块等外部系统提供统一行情数据接口。

---

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────┐
│                    External Modules                  │
│  ┌─────────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ 策略引擎     │  │ 下单模块  │  │ 风控/分析     │  │
│  │ (回测/实盘)  │  │          │  │              │  │
│  └──────┬──────┘  └────┬─────┘  └──────┬────────┘  │
└─────────┼──────────────┼───────────────┼───────────┘
          │              │               │
    ┌─────▼──────────────▼───────────────▼─────┐
    │           API Gateway (FastAPI)           │
    │  ┌────────┐  ┌────────┐  ┌───────────┐   │
    │  │ REST   │  │  WS    │  │ NATS(opt) │   │
    │  └───┬────┘  └───┬────┘  └─────┬─────┘   │
    └─────┼────────────┼──────────────┼─────────┘
          │            │              │
    ┌─────▼────────────▼──────────────▼─────────┐
    │          DataService (Core)                │
    │  ┌──────────┐  ┌─────────┐  ┌──────────┐  │
    │  │ MemCache │  │  SQLite  │  │ AKShare  │  │
    │  │ (hot)    │  │ (warm)   │  │ (cold)   │  │
    │  └──────────┘  └─────────┘  └──────────┘  │
    └────────────────────────────────────────────┘
```

### 数据分层策略

| 层级 | 介质 | 延迟 | 适用场景 |
|---|---|---|---|
| **Hot** | 内存 dict | 纳秒 | 最新N条K线、订阅推送 |
| **Warm** | SQLite | 毫秒 | 历史查询、回测数据 |
| **Cold** | AKShare API | 秒级 | 冷数据、强制刷新 |

---

## 2. 交易策略模块的接口需求

策略模块的核心数据需求：

```
策略模块需要:
  1. 历史K线 → 回测、计算指标（SMA, RSI, MACD...）
  2. 实时K线 → 信号触发（新K线生成时推送）
  3. 齐整的时间序列 → 按时间排序，无跳空/无缺失
  4. 多周期聚合 → 1m / 5m / 15m / 1h / 1d
```

### 2.1 REST API — 历史数据查询

```
### 查询K线
GET /api/v1/bars/{symbol}

Query Parameters:
  period     string    K线周期: 1m, 5m, 15m, 1h, 1d     (default: 1m)
  start      string    起始时间 ISO8601                   (default: 7天前)
  end        string    结束时间 ISO8601                   (default: now)
  limit      int       最大返回条数                       (default: 500, max: 10000)
  source     string    数据源: db, live, auto             (default: auto)

Response 200:
{
  "symbol": "AU2608.SHFE",
  "period": "1m",
  "count": 300,
  "bars": [
    {
      "ts": "2026-06-07T09:01:00+08:00",
      "open": 951.50,
      "high": 952.00,
      "low": 951.20,
      "close": 951.80,
      "volume": 100,
      "open_interest": 195000
    }
  ]
}
```

**source 参数说明**：

| 值 | 行为 | 用途 |
|---|---|---|
| `auto` | MemCache → SQLite → AKShare, 返回最先命中 | 策略默认 |
| `db` | 只查 SQLite, 无数据返回空 | 回测 |
| `live` | 直接从 AKShare 拉，不查缓存 | 验证数据 |

```
### 查询最新报价
GET /api/v1/quotes/{symbol}
GET /api/v1/quotes?symbols=AU2608.SHFE,RB2609.SHFE

### 查询品种元信息
GET /api/v1/symbols
GET /api/v1/symbols/{code}

Response:
{
  "code": "AU2608",
  "exchange": "SHFE",
  "full_symbol": "AU2608.SHFE",
  "name": "黄金",
  "contract_month": "202608",
  "multiplier": 1000,
  "price_tick": 0.02,
  "trading_hours": {
    "day": [["09:00","10:15"],["10:30","11:30"],["13:30","15:00"]],
    "night": [["21:00","02:30"]]
  }
}
```

### 2.2 WebSocket — 实时推送

```
### 订阅 / 取消订阅
→ {"type": "subscribe",   "symbols": ["AU2608.SHFE"], "channels": ["bar"]}
→ {"type": "unsubscribe", "symbols": ["AU2608.SHFE"]}

### 服务端推送
← {
    "type": "bar",
    "symbol": "AU2608.SHFE",
    "period": "1m",
    "ts": "2026-06-07T09:02:00+08:00",
    "open": 951.8, "high": 952.2, "low": 951.6, "close": 952.0,
    "volume": 56, "open_interest": 195010,
    "seq": 45231              ← 序列号，用于断线重连
  }

### 断线重连
→ {"type": "subscribe", "symbols": ["AU2608.SHFE"], "since_seq": 45231}
← （从 seq=45232 开始补发所有缺失的 bar）
```

### 2.3 周期聚合（在服务端完成）

策略需要多周期数据，但原始数据只有 1m。由后端聚合：

```python
def aggregate_bars(bars_1m: list[Bar], period: str) -> list[Bar]:
    """将1分钟K线聚合为 5m / 15m / 1h / 1d"""
    group_key = {
        "5m":  lambda ts: ts.replace(minute=(ts.minute // 5) * 5, second=0),
        "15m": lambda ts: ts.replace(minute=(ts.minute // 15) * 15, second=0),
        "1h":  lambda ts: ts.replace(minute=0, second=0),
        "1d":  lambda ts: ts.replace(hour=0, minute=0, second=0),
    }[period]
    
    groups: dict[int, Bar] = {}
    for bar in bars_1m:
        key = int(group_key(bar.ts_dt).timestamp() * 1e9)
        if key not in groups:
            groups[key] = Bar(ts_ns=key, open=bar.open, high=bar.high,
                              low=bar.low, close=bar.close, volume=0,
                              open_interest=bar.open_interest)
        else:
            g = groups[key]
            g.high = max(g.high, bar.high)
            g.low = min(g.low, bar.low)
            g.close = bar.close
            g.volume += bar.volume
            if bar.open_interest:
                g.open_interest = bar.open_interest
    return sorted(groups.values(), key=lambda b: b.ts_ns)
```

聚合不落库，每次查询时实时计算。数据量小（1m K线一天约300条），性能无瓶颈。

---

## 3. API v1 路由设计

```python
# server/routers/v1.py

router = APIRouter(prefix="/api/v1")

@router.get("/bars/{symbol}")
async def get_bars(
    symbol: str,
    period: Literal["1m","5m","15m","1h","1d"] = "1m",
    start: str | None = None,    # ISO8601
    end: str | None = None,      # ISO8601
    limit: int = Query(500, le=10000),
    source: Literal["auto","db","live"] = "auto",
): ...

@router.get("/quotes/{symbol}")
async def get_quote(symbol: str): ...

@router.get("/quotes")
async def get_quotes(symbols: str = ""): ...  # comma-separated

@router.get("/symbols")
async def list_symbols(): ...

@router.get("/symbols/{code}")
async def symbol_meta(code: str): ...
```

---

## 4. 数据流 & 状态管理

```
                    策略模块
                       │
           ┌───────────┼───────────┐
           │           │           │
      GET /bars    WS bar      GET /bars
      (回测)      (实时信号)   (初始化/补数据)
           │           │           │
           ▼           ▼           ▼
      ┌─────────────────────────────────────┐
      │         DataService                 │
      │                                     │
      │  1. source=auto:                    │
      │     MemCache hit? → 立即返回        │
      │     SQLite hit?   → 返回+缓存       │
      │     都不中?       → AKShare拉+落库  │
      │                                     │
      │  2. new bar 到达时:                 │
      │     MemCache 更新                   │
      │     WS 广播所有订阅者               │
      │     SQLite upsert                   │
      └─────────────────────────────────────┘
```

### 关键决策

1. **AKShare 不走前端链路** — `source=live` 只为外部模块提供，前端只查 DB
2. **聚合不落库** — 避免数据冗余和一致性问题，查的时候实时聚合
3. **DB 定时修复** — 发现数据缺失时，调度器自动补拉（通过 quality report 驱动）
4. **交易时段外返回缓存** — `source=auto` 在非交易时不会去调 AKShare

---

## 5. 实现计划

| Step | 内容 | 交付 |
|---|---|---|
| **1** | 迁移到 `C:\futures_demo`，更新路径 | 稳定运行 |
| **2** | 实现 `server/routers/v1.py` — `GET /api/v1/bars/{symbol}` | 策略可用 |
| **3** | 实现周期聚合函数 | 多周期支持 |
| **4** | 实现 `GET /api/v1/quotes`, `/symbols` | 元数据支持 |
| **5** | WS 升级 — 多频道 + seq 断线重连 | 实时信号 |
| **6** | `source=live` 直调 AKShare | 冷数据查询 |
| **7** | 删除旧 `_check_gaps.py` `_inspect_akshare.py` 临时脚本 | 清理 |
