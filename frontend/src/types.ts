/** K线聚合周期 */
export type Period = '1m' | '5m' | '15m' | '1h' | '1d'

/** 时间范围预设 */
export type TimeRangePreset = '1d' | '3d' | '7d' | '30d' | 'custom'

/** 时间范围 */
export interface TimeRange {
  preset: TimeRangePreset
  start: string      // ISO8601
  end: string        // ISO8601
  period: Period     // 自动选择的聚合周期
}

/** K 线数据 */
export interface KLineData {
  ts_ns: number
  ts: string           // "2026-06-07 09:01:00"
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover?: number
  open_interest?: number | null
  source?: string
}

/** 品种信息 */
export interface SymbolInfo {
  code: string
  variety: string
  exchange: string
  full_symbol: string
  display_name: string
  contract_month: string
}

/** 报价摘要 */
export type QuoteData = KLineData

/** 数据质量报告 */
export interface QualityReport {
  symbol: string
  total_bars: number
  gaps: number
  max_gap_seconds: number
  outliers: number
  zero_volume: number
  is_healthy: boolean
}

/** 服务状态 */
export interface ServerStatus {
  status: string
  symbols_count: number
  last_poll_ts: number | null
  last_update_ts: number | null
  last_update_str: string
  is_trading_time: boolean
  data_dir: string
}

/** WebSocket 消息类型 */
export type WSMessage =
  | { type: 'kline_update'; symbol: string; bars: KLineData[] }
  | { type: 'status'; status: string; message: string }
  | { type: 'error'; message: string }
  | { type: 'ping' }
  | { type: 'pong' }

/** WebSocket 连接状态 */
export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'
