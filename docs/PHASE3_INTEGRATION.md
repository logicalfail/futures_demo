# Phase 3: Integration & E2E Testing

## 1. 阶段范围

前后端联调测试，覆盖：
- 后端 REST API 全部端点（复用 Phase 1 测试）
- WebSocket 订阅/推送全链路
- 前端构建产物在 FastAPI 静态文件服务下的可用性
- 定时调度器 + WS 广播的数据流完整性
- 手动刷新触发流程

## 2. 测试结构

```
tests/
├── test_server_phase1.py          # Phase 1 单体测试（10个）
└── test_integration_phase3.py     # Phase 3 集成测试（新增）
```

## 3. 测试用例

### 3.1 REST API 过路测试（5个）
- `test_serve_frontend_index` — 访问 `/` 返回 HTML
- `test_serve_frontend_assets` — 访问 JS/CSS 返回 200
- `test_api_symbols_format` — 验证品种列表结构
- `test_api_kline_with_ws_subscribe` — K线数据通过WS订阅推送后通过REST获取
- `test_api_quotes_batch` — 批量获取报价

### 3.2 WebSocket 全链路测试（4个）
- `test_ws_subscribe_receives_kline` — 订阅品种后立即收到kline_update
- `test_ws_subscribe_multiple_symbols` — 多品种订阅
- `test_ws_unsubscribe` — 取消订阅后不再收到更新
- `test_ws_manual_refresh_triggers_poll` — 手动刷新触发轮询

### 3.3 数据流完整性（3个）
- `test_kline_data_structure` — K线数据字段完整
- `test_quote_data_order` — 报价按时间升序返回
- `test_subscribe_then_kline_match` — WS推送的K线与REST查询一致

## 4. 运行方式

```bash
# 设置环境变量
set PYTHONPATH=C:\tmp\futures_demo

# 运行全部测试
python -m pytest tests/ -v

# 单独运行 Phase 3
python -m pytest tests/test_integration_phase3.py -v
```

## 5. 测试数据库

使用独立测试数据库 `futures_demo/data/futures_1m_test.db`（与 Phase 1 相同），
不污染生产数据。
