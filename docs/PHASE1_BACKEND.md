# Phase 1: Backend Server Design

## 1. 阶段范围

构建 FastAPI WebSocket 服务层，包含：
- WebSocket 连接管理器（连接池 + 订阅管理）
- REST API（历史K线查询 + 品种列表 + 手动刷新）
- 数据服务层（查询 + 缓存 + 最新价提取）
- 定时调度器（每分钟轮询推送）
- 服务配置

**不包含**：前端开发（Phase 2）

## 2. 模块设计

### 2.1 `server/config.py`

服务配置，YAML 加载：
```python
server:
  host: "127.0.0.1"
  port: 8000
  frontend_dir: "./frontend/dist"  # 构建后的前端静态文件

scheduler:
  interval_seconds: 60
  trading_hours_only: true

storage:
  type: "sqlite"  # 或 "timescaledb"
  path: "./data/futures_1m.db"
```

### 2.2 `server/connection_manager.py`

```python
class ConnectionManager:
    """
    WebSocket 连接池
    - active_connections: dict[WebSocket, set[str]]  # 连接 → 订阅的symbols
    - 方法: connect, disconnect, subscribe, unsubscribe
    - 广播: broadcast_kline_update(symbol, bars)
    - 心跳: ping_pong (30s间隔)
    """
```

### 2.3 `server/data_service.py`

```python
class DataService:
    """
    数据服务
    - get_symbols() -> list[str]  # 从config获取品种列表
    - get_kline(symbol, limit=1000) -> list[MarketBar]  # 历史K线
    - get_latest_bars(symbol) -> list[MarketBar]  # 当日最新K线
    - poll_new_data() -> dict[symbol, list[MarketBar]]  # 轮询新数据
    - refresh_all() -> int  # 强制刷新所有品种
    - get_quality_report() -> list  # 数据质量摘要
    """
```

### 2.4 `server/scheduler.py`

```python
class DataScheduler:
    """
    定时调度器
    - 使用 asyncio 实现，不依赖外部调度库
    - start() / stop()
    - 每分钟检查+拉取+推送
    - 识别交易时段，非交易时段跳过
    """
```

### 2.5 `server/app.py`

```python
# FastAPI 应用
# - /ws → WebSocket 端点
# - /api/symbols → GET 品种列表
# - /api/kline/{symbol} → GET 历史K线
# - /api/refresh → POST 手动刷新
# - /api/status → GET 服务状态
# - / → 前端静态文件
```

## 3. WebSocket 消息协议

详见 `ARCHITECTURE.md §3.1`

## 4. 数据流

```
Scheduler (每分钟)
    → DataService.poll_new_data()
        → fetcher.fetch_minute_bars(symbol)
        → storage.upsert_bars(new_bars)
        → 返回 {symbol: [new_bars]}
    → ConnectionManager.broadcast_kline_update(symbol, bars)
        → 遍历 active_connections，只推已订阅对应symbol的连接
```

## 5. 错误处理

- AKShare 拉取失败：记录错误，不影响已有数据，下次重试
- WebSocket 断开：自动清理连接，不需要客户端主动关闭
- 数据库错误：重试1次，仍失败则报警到状态栏

## 6. 测试计划

### 6.1 后端 E2E 测试

1. 启动 FastAPI server
2. 验证 REST API：`GET /api/symbols`, `GET /api/kline/AU2608.SHFE`
3. 验证 WebSocket：连接 → subscribe → 等待推送 → 接收 kline_update
4. 验证手动刷新：POST /api/refresh → WS 收到更新
5. 验证定时调度：等待1分钟后确认收到推送

### 6.2 工具

- `curl` / `httpx` 测试 REST
- `websockets` (Python) 测试 WS
- 日志断言
