# API 接口文档

> Futures Terminal — 数据服务接口

---

## 概览

| 类型 | 基础路径 | 用途 |
|------|---------|------|
| REST API v1 | `/api/v1/` | 外部模块接口（交易策略、风控、订单执行） |
| REST API (legacy) | `/api/` | 前端旧版接口 |
| WebSocket | `/ws` | 实时数据推送 |
| 静态文件 | `/` | 前端 SPA |

服务运行后访问 `http://<host>:<port>/docs` 可查看 Swagger 交互式文档。

---

## REST API v1（推荐）

设计目标：为策略引擎、风控系统、订单执行模块提供干净、可聚合的 K线数据。

### 基础路径

```
/api/v1/
```

### `GET /api/v1/bars/{symbol}` — K线数据

获取品种的分钟 K线，支持多周期聚合和多数据源。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 合约代码，如 `RB2609`、`AU2608.SHFE` |

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `period` | string | `1m` | 聚合周期：`1m` / `5m` / `15m` / `1h` / `1d` |
| `start` | string | 7天前 | 起始时间，ISO8601 格式：`2026-06-01` 或 `2026-06-01T09:00:00` |
| `end` | string | 当前 | 结束时间，ISO8601 格式 |
| `limit` | int | 500 | 返回条数上限（1–10000） |
| `source` | string | `auto` | 数据源：`auto`（DB优先→AKShare补）、`db`（仅DB）、`live`（直拉AKShare） |

#### 返回示例

```json
{
  "symbol": "RB2609.SHFE",
  "period": "5m",
  "start": "2026-06-05 09:00:00",
  "end": "2026-06-07 15:00:00",
  "count": 120,
  "source": "auto",
  "bars": [
    {
      "ts": "2026-06-05 09:00:00",
      "ts_ns": 1780606800000000000,
      "open": 3150.0,
      "high": 3155.0,
      "low": 3148.0,
      "close": 3153.0,
      "volume": 1234,
      "open_interest": 1520000
    }
  ]
}
```

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | string | K线时间（北京时间，格式 `%Y-%m-%d %H:%M:%S`） |
| `ts_ns` | int64 | 纳秒级 Unix 时间戳 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `volume` | int | 成交量（手） |
| `open_interest` | int or null | 持仓量 |

#### source 参数说明

| source | 行为 |
|--------|------|
| `auto`（默认） | 先查 DB，如果 DB 为空则自动 fallback 到 AKShare 直拉 |
| `db` | 仅从本地 DB 查询，不请求外部 API |
| `live` | 直接从 AKShare 拉取最新 5 天数据，不查 DB |

> `source=live` 时跳过交易时段检查，任何时候都可以拉取。

---

### `GET /api/v1/quotes/{symbol}` — 最新报价

获取单个品种的最新报价（最后一条 K线的 close 价）。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 合约代码 |

#### 返回示例

```json
{
  "symbol": "RB2609",
  "quote": {
    "ts_ns": 1780876800000000000,
    "ts": "2026-06-07 08:00:00",
    "open": 3170.0,
    "high": 3172.0,
    "low": 3168.0,
    "close": 3171.0,
    "volume": 521,
    "open_interest": 1523500
  }
}
```

---

### `GET /api/v1/quotes?symbols=...` — 批量报价

获取多个品种的最新报价。

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `symbols` | string | 空=全部 | 逗号分隔的品种列表，如 `RB2609,AU2608,AG2608` |

#### 返回示例

```json
{
  "count": 3,
  "quotes": {
    "RB2609.SHFE": { "ts": "2026-06-07 08:00:00", "close": 3171.0, ... },
    "AU2608.SHFE": { "ts": "2026-06-07 08:00:00", "close": 556.8, ... },
    "AG2608.SHFE": { "ts": "2026-06-07 08:00:00", "close": 7850.0, ... }
  }
}
```

---

### `GET /api/v1/symbols` — 品种列表

获取所有可用的品种信息。

#### 返回示例

```json
{
  "symbols": [
    {
      "code": "RB2609",
      "variety": "RB",
      "exchange": "SHFE",
      "full_symbol": "RB2609.SHFE",
      "display_name": "RB2609 (SHFE)",
      "contract_month": "2609"
    }
  ]
}
```

---

### `GET /api/v1/symbols/{code}` — 品种元信息

获取单个品种的合约乘数、最小变动价位等元信息。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | string | 品种代码，如 `RB2609` |

#### 返回示例

```json
{
  "code": "RB2609",
  "variety": "RB",
  "exchange": "SHFE",
  "full_symbol": "RB2609.SHFE",
  "contract_month": "2609",
  "multiplier": 10
}
```

---

## Legacy REST API

前端使用的旧版接口，功能较 v1 简单。路径前缀 `/api/`。

### `GET /api/symbols`

返回品种列表（同 `/api/v1/symbols`）。

### `GET /api/kline/{symbol}?limit=1000&days_back=7`

获取历史 K线（仅 1m，无聚合）。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `limit` | int | 1000 | 最大条数（1–10000） |
| `days_back` | int | 7 | 回溯天数（1–90） |

### `GET /api/quote/{symbol}`

获取最新报价。

### `GET /api/quotes`

获取所有品种的最新报价。

### `POST /api/refresh`

手动触发数据刷新。

### `GET /api/status`

服务状态信息。

```json
{
  "status": "running",
  "symbols_count": 13,
  "last_poll_ts": 1780876800000000000,
  "last_update_ts": 1780876800000000000,
  "last_update_str": "08:00:00",
  "is_trading_time": false,
  "data_dir": "C:\\futures_demo\\data\\futures_1m.db"
}
```

### `GET /api/quality`

数据质量报告。返回每个品种的条数、间隔缺口、异常值等。

```json
{
  "reports": [
    {
      "symbol": "RB2609.SHFE",
      "total_bars": 1023,
      "gaps": 0,
      "max_gap_seconds": 60,
      "outliers": 0,
      "zero_volume": 0,
      "is_healthy": true
    }
  ]
}
```

---

## WebSocket — 实时数据

### 连接地址

```
ws://<host>:<port>/ws
```

### 客户端 → 服务端消息

#### subscribe — 订阅品种

```json
{ "type": "subscribe", "symbols": ["RB2609", "AU2608"] }
```

成功后立即推送该品种的最新 100 根 K线。

#### unsubscribe — 取消订阅

```json
{ "type": "unsubscribe", "symbols": ["RB2609"] }
```

#### manual_refresh — 手动触发刷新

```json
{ "type": "manual_refresh" }
```

#### ping — 心跳

```json
{ "type": "ping" }
```

### 服务端 → 客户端消息

#### kline_update — K线更新

```json
{
  "type": "kline_update",
  "symbol": "RB2609",
  "bars": [
    { "ts_ns": ..., "ts": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "open_interest": ... }
  ]
}
```

#### status — 状态通知

```json
{ "type": "status", "status": "polling", "message": "Fetching new data..." }
```

可能的状态值：`polling`、`idle`、`error`。

#### pong — 心跳回复

```json
{ "type": "pong" }
```

### 完整交互流程

```
1. Client → Server:  {"type": "subscribe", "symbols": ["RB2609"]}
2. Server → Client:  {"type": "kline_update", "symbol": "RB2609", "bars": [...]}
3. ...每60秒调度器轮询...
4. Server → Client:  {"type": "kline_update", "symbol": "RB2609", "bars": [新数据]}
5. Client → Server:  {"type": "ping"}
6. Server → Client:  {"type": "pong"}
7. Client → Server:  {"type": "unsubscribe", "symbols": ["RB2609"]}
```

---

## 调用示例

### curl

```bash
# 获取螺纹钢 5分钟 K线
curl "http://127.0.0.1:8000/api/v1/bars/RB2609?period=5m&limit=10"

# 从AKShare直拉实时数据
curl "http://127.0.0.1:8000/api/v1/bars/AU2608?source=live&period=1m&limit=5"

# 查询指定时间范围
curl "http://127.0.0.1:8000/api/v1/bars/RB2609?start=2026-06-05T09:00:00&end=2026-06-05T15:00:00"

# 批量报价
curl "http://127.0.0.1:8000/api/v1/quotes?symbols=RB2609,AU2608,AG2608"

# 品种列表
curl "http://127.0.0.1:8000/api/v1/symbols"

# 品种元信息
curl "http://127.0.0.1:8000/api/v1/symbols/RB2609"

# WebSocket (wscat 需安装: npm install -g wscat)
wscat -c ws://127.0.0.1:8000/ws
> {"type": "subscribe", "symbols": ["RB2609"]}
```

### Python

```python
import urllib.request, json

base = "http://127.0.0.1:8000"

# 获取 K线
resp = urllib.request.urlopen(f"{base}/api/v1/bars/RB2609?period=5m&limit=10")
data = json.loads(resp.read())
print(f"Bars: {data['count']}")

# 使用 websockets 库连接 WebSocket
import asyncio, websockets

async def subscribe():
    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        await ws.send(json.dumps({"type": "subscribe", "symbols": ["RB2609"]}))
        msg = await ws.recv()
        print(msg)

asyncio.run(subscribe())
```

### JavaScript

```javascript
// fetch API
const base = 'http://127.0.0.1:8000';
const res = await fetch(`${base}/api/v1/bars/RB2609?period=5m&limit=10`);
const data = await res.json();
console.log(data);

// WebSocket
const ws = new WebSocket('ws://127.0.0.1:8000/ws');
ws.onopen = () => ws.send(JSON.stringify({type: 'subscribe', symbols: ['RB2609']}));
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

---

## 数据说明

### 品种代码格式

| 格式 | 示例 | 说明 |
|------|------|------|
| 短代码 | `RB2609` | 品种字母+交割年月 |
| 完整代码 | `RB2609.SHFE` | 短代码+交易所后缀 |

后端自动补全：传入 `RB2609` 自动识别为 `RB2609.SHFE`。

### 时间戳

- 所有时间字段 `ts` 均为 **北京时间（UTC+8）**
- `ts_ns` 为纳秒级 Unix 时间戳（int64），便于精确计算和排序
- K线时间 = 该周期的起始时间（如 `2026-06-05 09:00:00` 的 5m K线覆盖 09:00–09:04）

### 交易时段检查

自动调度的数据轮询（60s 间隔）仅在交易时段内工作：
- 日盘：09:00–10:15 / 10:30–11:30 / 13:30–15:00
- 夜盘：21:00–02:30（最宽覆盖）

手动触发的操作（`source=live`、`POST /api/refresh`）跳过时间检查，随时可用。

---

## 错误处理

| HTTP 状态 | 说明 |
|-----------|------|
| 200 | 成功（列表为空时也返回 200） |
| 404 | 路径不存在 / 无效品种代码 |
| 422 | 参数校验失败（如 limit 超范围） |
| 500 | 服务内部错误（连接池耗尽、DB 损坏等） |

所有错误响应均包含 `detail` 字段描述具体错误：

```json
{ "detail": "Invalid symbol format: INVALID" }
```
