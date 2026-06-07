# Phase 2: Frontend Design

## 1. 阶段范围

构建 React + Vite + ECharts 前端，包含：
- K线图表组件（ECharts candlestick）
- 实时报价表格
- 品种选择器（单选/多选）
- 状态栏（连接/数据状态）
- WebSocket Hooks
- HTTP API 封装

## 2. 组件树

```
App
├── AppLayout
│   ├── StatusBar (连接状态 + 最后更新时间 + 品种数)
│   ├── SymbolSelector (品种下拉多选)
│   ├── KLineChart (ECharts K线图)
│   └── QuoteTable (实时报价表格)
└── useWebSocket (WebSocket 连接管理)
    └── useDataApi (HTTP API 封装)
```

## 3. 数据流

```
[WebSocket] → useWebSocket hook
    ↓ dispatch kline_update / status
[React State] (symbols, klineData, quotes, connectionStatus)
    ↓ props
KLineChart ← symbol selector
QuoteTable ← all quotes
StatusBar ← connection status + last update time
```

## 4. 组件接口

### KLineChart
- Props: `symbol: string`, `bars: KLineData[]`
- 使用 ECharts candlestick 渲染
- 自动适配 Y 轴范围
- 显示成交量柱状图

### QuoteTable
- Props: `quotes: QuoteData[]`
- 列：品种代码 | 最新价 | 涨跌幅 | 成交量 | 持仓量 | 更新时间
- 颜色：涨红跌绿

### SymbolSelector
- Props: `symbols: SymbolInfo[]`, `selected: string[]`, `onChange: (selected) => void`
- 多选下拉框

### StatusBar
- Props: `status: string`, `lastUpdate: string`, `symbolCount: number`
- 显示连接状态指示灯 + 文字

## 5. WebSocket 消息处理

```typescript
// onMessage dispatch
switch(msg.type) {
  case 'kline_update':
    updateSymbolBars(msg.symbol, msg.bars);
    break;
  case 'status':
    updateConnectionStatus(msg.status);
    break;
  case 'ping':
    send('{"type":"pong"}');
    break;
}
```
