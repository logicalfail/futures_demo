# Futures Terminal — 模拟交易员操作终端设计与架构

## 1. 项目概览

### 1.1 目标
构建一个模拟交易员操作交易终端的软件，核心能力：
- 从公开财经数据源获取期货行情数据（分钟K线）
- 通过 WebSocket 实时推送至前端展示
- 支持定时自动更新 + 手动刷新
- K线图 + 实时报价表 + 品种管理

### 1.2 约束
- 数据源：AKShare（聚合新浪财经/东方财富），非官方，延迟1-3秒
- 实时性：分钟级（1分钟轮询）
- 标的数量：10-20个期货主力合约
- 运行环境：Windows 本地一体化部署
- 存储：SQLite（开发） / TimescaleDB（生产）

---

## 2. 系统架构

### 2.1 分层架构图

```
┌────────────────────────────────────────────────────────────┐
│                    Presentation Layer                       │
│     React + Vite + ECharts + TypeScript                    │
│  ┌─────────┐  ┌──────────┐  ┌──────┐  ┌───────────────┐  │
│  │ KLine    │  │ Quote    │  │Symbol│  │ Status        │  │
│  │ Chart    │  │ Table    │  │Select│  │ Bar           │  │
│  └────┬────┘  └────┬─────┘  └──┬───┘  └──────┬────────┘  │
│       └────────────┴──────────┴──────────────┘           │
│                         │ WebSocket (ws://)               │
│                         │ HTTP REST (GET)                 │
├─────────────────────────┴──────────────────────────────────┤
│                    Service Layer (FastAPI)                  │
│  ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ WebSocket    │ │ REST API │ │ Scheduler │ │ Data     │ │
│  │ Manager      │ │ Router   │ │ (定时轮询) │ │ Service  │ │
│  │ (连接池)      │ │          │ │          │ │ (Cache)  │ │
│  └──────┬───────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│         │              │            │             │       │
├─────────┴──────────────┴────────────┴─────────────┴───────┤
│                    Data Layer                               │
│  ┌──────────────────┐  ┌──────────────────────────────┐   │
│  │ futures_demo     │  │ AKShare (Sina 数据源)         │   │
│  │ (fetcher/storage │  │                              │   │
│  │  /quality/models)│  │                              │   │
│  └────────┬─────────┘  └──────────────────────────────┘   │
│           │                                                │
│  ┌────────┴─────────┐                                      │
│  │ SQLite / TimescaleDB                                   │
│  │ (bars_1m 时序表)  │                                      │
│  └──────────────────┘                                      │
└────────────────────────────────────────────────────────────┘
```

### 2.2 组件职责

| 层 | 组件 | 职责 |
|----|------|------|
| **展示层** | `KLineChart` | ECharts K线图，展示分钟OHLC数据 |
| | `QuoteTable` | 实时报价表（最新价、涨跌幅、成交量、持仓量） |
| | `SymbolSelector` | 品种下拉选择器，多选/单选 |
| | `StatusBar` | 连接状态、最后更新时间、数据质量指示 |
| | `useWebSocket` | WebSocket 连接管理与消息分发 |
| **服务层** | `WebSocketManager` | 连接池管理、广播/单播消息 |
| | `Scheduler` | 定时轮询调度器（每分钟触发抓取+推送） |
| | `DataService` | 数据查询+缓存+格式转换 |
| | REST API | 历史K线查询、品种列表、手动刷新触发 |
| **数据层** | `fetcher.py` | AKShare 数据获取 |
| | `storage.py` | SQLite/TimescaleDB 存储抽象 |
| | `models.py` | MarketBar Pydantic 数据模型 |
| | `quality.py` | 数据质量检查 |

### 2.3 目录结构

```
C:\tmp\futures_demo\
├── .omo/plans/              # 设计文档
│   └── ARCHITECTURE.md      # 本文件
├── docs/                    # 模块设计文档（按阶段）
│   ├── DECISIONS.md
│   ├── PHASE1_BACKEND.md
│   ├── PHASE2_FRONTEND.md
│   └── PHASE3_INTEGRATION.md
├── futures_demo/             # 数据层（已有）
│   ├── __init__.py
│   ├── config.py / config.yaml
│   ├── fetcher.py
│   ├── storage.py
│   ├── quality.py
│   ├── models.py
│   └── vnpy_adapter.py
├── server/                   # FastAPI 服务层
│   ├── __init__.py
│   ├── app.py               # 主入口 + WebSocket + REST
│   ├── config.py            # 服务配置
│   ├── data_service.py      # 数据查询/缓存服务
│   ├── connection_manager.py # WebSocket 连接池
│   └── scheduler.py         # 定时轮询调度器
├── frontend/                 # React 前端
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx / App.tsx / App.css
│       ├── types.ts
│       ├── api/dataService.ts       # HTTP API 封装
│       ├── hooks/useWebSocket.ts    # WebSocket Hook
│       └── components/
│           ├── KLineChart.tsx       # ECharts K线图
│           ├── QuoteTable.tsx       # 实时报价表
│           ├── SymbolSelector.tsx   # 品种选择器
│           └── StatusBar.tsx        # 状态栏
├── config.yaml                 # 数据层配置
├── server_config.yaml          # 服务层配置
├── run.py                      # 统一启动脚本
├── pipeline.py
├── demo.py
├── requirements.txt
└── requirements-server.txt     # 服务依赖
```

---

## 3. 数据流设计

### 3.1 WebSocket 消息协议

**Server → Client**
```json
{
  "type": "kline_update",
  "symbol": "AU2608.SHFE",
  "bars": [
    {"ts_ns": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "hold": ...}
  ]
}
```
```json
{"type": "status", "status": "connected|polling|error", "message": "..."}
```

**Client → Server**
```json
{"type": "subscribe", "symbols": ["AU2608", "RB2609"]}
{"type": "unsubscribe", "symbols": ["AU2608"]}
{"type": "manual_refresh"}
```

### 3.2 数据更新流程

```
[每分钟] Scheduler 触发
    ↓
[DataService] futures_demo.fetcher.fetch_minute_bars(symbol)
    ↓
[DataService] dedup + upsert to SQLite/TimescaleDB
    ↓
[DataService] 提取最新K线
    ↓
[WebSocketManager] broadcast kline_update 到所有已订阅客户端的连接
    ↓
[前端 useWebSocket] 接收消息 → 更新 ECharts + 报价表
```

---

## 4. 技术决策日志

| # | 决策 | 方案 | 理由 |
|---|------|------|------|
| 1 | 前端框架 | React + Vite | 用户选择，生态最丰富 |
| 2 | 图表库 | ECharts | 用户选择，中文文档完善 |
| 3 | 后端框架 | FastAPI | 原生WS支持、async、自动文档 |
| 4 | 存储 | SQLite(dev) → TimescaleDB(prod) | 用户选择升级到TSDB |
| 5 | 更新策略 | 1分钟轮询 + WebSocket推送 | 分钟级数据无须tick推送 |
| 6 | 部署 | 本地一体化 | 一个命令启动全部 |
| 7 | 语言 | Python(后端) + TypeScript(前端) | 数据层Python生态，前端TS类型安全 |

---

## 5. 质量属性

- **可维护性**：模块化分层，每层可以独立替换
- **可观测性**：WebSocket Status 消息 + 前端状态栏
- **容错**：AKShare 失败不影响前端显示已有数据
- **性能**：SQLite WAL模式，单品种千条K线查询 < 10ms
