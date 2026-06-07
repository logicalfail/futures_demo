/**
 * HTTP API 封装
 * - 获取品种列表
 * - 获取历史K线
 * - 手动刷新
 * - 服务状态
 */

import type { SymbolInfo, KLineData, ServerStatus, QualityReport, Period } from '../types'

const BASE = ''  // 开发时 vite proxy 处理，生产时同域

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(`${BASE}${url}`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json()
}

export async function getSymbols(): Promise<SymbolInfo[]> {
  const data = await fetchJSON<{ symbols: SymbolInfo[] }>('/api/symbols')
  return data.symbols
}

export async function getKLine(symbol: string, limit = 500, daysBack = 7): Promise<KLineData[]> {
  const data = await fetchJSON<{ symbol: string; bars: KLineData[] }>(
    `/api/kline/${symbol}?limit=${limit}&days_back=${daysBack}`
  )
  return data.bars
}

export async function refreshData(): Promise<void> {
  await fetchJSON('/api/refresh')
}

export async function getStatus(): Promise<ServerStatus> {
  return fetchJSON<ServerStatus>('/api/status')
}

export async function getQuality(): Promise<QualityReport[]> {
  const data = await fetchJSON<{ reports: QualityReport[] }>('/api/quality')
  return data.reports
}

export async function getQuote(symbol: string): Promise<KLineData | null> {
  const data = await fetchJSON<{ symbol: string; quote: KLineData | null }>(`/api/quote/${symbol}`)
  return data.quote
}

/** 使用 v1 API 按时间范围 + 聚合周期获取 K线 */
export async function getBarsV1(
  symbol: string,
  period: Period,
  start: string,
  end: string,
  limit = 5000,
): Promise<KLineData[]> {
  const params = new URLSearchParams({
    period,
    start,
    end,
    limit: String(limit),
    source: 'auto',
  })
  const data = await fetchJSON<{ symbol: string; bars: KLineData[]; count: number }>(
    `/api/v1/bars/${symbol}?${params}`
  )
  return data.bars
}
