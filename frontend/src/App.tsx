/**
 * 期货行情终端 - 主应用
 * - K线图（中央）
 * - 报价表格（右侧）
 * - 品种选择器 + 时间范围选择器（上方）
 * - 状态栏（底部）
 */

import React, { useEffect, useState, useCallback, useRef } from 'react'
import KLineChart from './components/KLineChart'
import QuoteTable from './components/QuoteTable'
import SymbolSelector from './components/SymbolSelector'
import StatusBar from './components/StatusBar'
import { useWebSocket } from './hooks/useWebSocket'
import { getSymbols, getDominantSymbols, getKLine, getStatus, getQuote, getBarsV1 } from './api/dataService'
import type { SymbolInfo, KLineData, TimeRangePreset, Period } from './types'

// ── 时间范围预设 ──
interface TimeRangeOption {
  preset: TimeRangePreset
  label: string
  days: number
  period: Period
}

const RANGE_OPTIONS: TimeRangeOption[] = [
  { preset: '1d',  label: '1日',  days: 1,  period: '1m' },
  { preset: '3d',  label: '3日',  days: 3,  period: '5m' },
  { preset: '7d',  label: '1周',  days: 7,  period: '15m' },
  { preset: '30d', label: '1月',  days: 30, period: '1h' },
]

function isoNow(): string {
  const d = new Date()
  d.setSeconds(0, 0)
  return d.toISOString().slice(0, 16).replace('T', 'T')
}

function isoPast(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  d.setSeconds(0, 0)
  return d.toISOString().slice(0, 16).replace('T', 'T')
}

export default function App() {
  // ---- 品种数据 ----
  const [symbols, setSymbols] = useState<SymbolInfo[]>([])
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [currentSymbol, setCurrentSymbol] = useState<string | null>(null)
  const [kLineData, setKLineData] = useState<KLineData[]>([])
  const [kLinePeriod, setKLinePeriod] = useState<Period>('1m')
  const [quotes, setQuotes] = useState<Map<string, KLineData>>(new Map())
  const [lastUpdate, setLastUpdate] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  // ---- 时间范围状态 ----
  const [rangePreset, setRangePreset] = useState<TimeRangePreset>('3d')
  const [customStart, setCustomStart] = useState(isoPast(7))
  const [customEnd, setCustomEnd] = useState(isoNow())
  const [loading, setLoading] = useState(false)

  // ---- 初始加载：使用主力合约 ----
  useEffect(() => {
    getDominantSymbols().then(syms => {
      setSymbols(syms)
      if (syms.length > 0) {
        const first = syms[0].full_symbol
        setSelectedSymbols([first])
        setCurrentSymbol(first)
        loadKLineByRange(first, '3d')
        loadQuote(first)
      }
    })
    loadStatus()
  }, [])

  // ---- K线加载（按时间范围） ----
  const loadKLineByRange = useCallback(async (
    symbol: string,
    preset: TimeRangePreset,
    cStart?: string,
    cEnd?: string,
  ) => {
    setLoading(true)
    try {
      let start: string, end: string, period: Period

      if (preset === 'custom' && cStart && cEnd) {
        start = cStart
        end = cEnd
        // 根据自定义范围天数选择周期
        const days = (new Date(end).getTime() - new Date(start).getTime()) / 86400000
        if (days <= 1) period = '1m'
        else if (days <= 3) period = '5m'
        else if (days <= 14) period = '15m'
        else period = '1h'
      } else {
        const opt = RANGE_OPTIONS.find(r => r.preset === preset)!
        end = isoNow()
        start = isoPast(opt.days)
        period = opt.period
      }

      setKLinePeriod(period)
      const bars = await getBarsV1(symbol, period, start, end)
      setKLineData(bars)
    } catch (e) {
      console.warn('Failed to load KLine:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  // ---- 其他数据加载 ----
  const loadQuote = async (symbol: string) => {
    try {
      const quote = await getQuote(symbol)
      if (quote) {
        setQuotes(prev => {
          const next = new Map(prev)
          next.set(symbol, quote)
          return next
        })
      }
    } catch { /* ignore */ }
  }

  const loadAllQuotes = async () => {
    const newQuotes = new Map<string, KLineData>()
    for (const sym of selectedSymbols) {
      try {
        const quote = await getQuote(sym)
        if (quote) newQuotes.set(sym, quote)
      } catch { /* skip */ }
    }
    setQuotes(newQuotes)
  }

  const loadStatus = async () => {
    try {
      const status = await getStatus()
      if (status.last_update_str) {
        setLastUpdate(status.last_update_str)
      }
    } catch { /* ignore */ }
  }

  // ---- 切换品种 ----
  const handleSelectSymbol = useCallback((symbol: string) => {
    setCurrentSymbol(symbol)
    loadKLineByRange(symbol, rangePreset, customStart, customEnd)
  }, [rangePreset, customStart, customEnd, loadKLineByRange])

  // ---- 品种选择变更 ----
  const handleSymbolsChange = useCallback((selected: string[]) => {
    setSelectedSymbols(selected)
    if (currentSymbol && !selected.includes(currentSymbol) && selected.length > 0) {
      setCurrentSymbol(selected[0])
      loadKLineByRange(selected[0], rangePreset, customStart, customEnd)
    }
    if (selected.length === 0) {
      setCurrentSymbol(null)
      setKLineData([])
    }
  }, [currentSymbol, rangePreset, customStart, customEnd, loadKLineByRange])

  // ---- 时间范围切换 ----
  const handleRangeChange = useCallback((preset: TimeRangePreset) => {
    setRangePreset(preset)
    if (currentSymbol) {
      loadKLineByRange(currentSymbol, preset, customStart, customEnd)
    }
  }, [currentSymbol, customStart, customEnd, loadKLineByRange])

  const handleCustomRange = useCallback(() => {
    if (currentSymbol) {
      loadKLineByRange(currentSymbol, 'custom', customStart, customEnd)
    }
  }, [currentSymbol, customStart, customEnd, loadKLineByRange])

  // ---- WebSocket 回调 ----
  const handleKLineUpdate = useCallback((symbol: string, bars: KLineData[]) => {
    if (symbol === currentSymbol) {
      setKLineData(prev => {
        const existing = new Map(prev.map(b => [b.ts_ns, b]))
        for (const bar of bars) existing.set(bar.ts_ns, bar)
        return Array.from(existing.values()).sort((a, b) => a.ts_ns - b.ts_ns)
      })
    }
    if (bars.length > 0) {
      const latest = bars[bars.length - 1]
      setQuotes(prev => {
        const next = new Map(prev)
        next.set(symbol, latest)
        return next
      })
    }
  }, [currentSymbol])

  const handleStatusMsg = useCallback((status: string, message: string) => {
    if (status === 'update' || status === 'poll') {
      setLastUpdate(message || new Date().toLocaleString('zh-CN'))
    }
  }, [])

  const { connectionStatus, subscribe, unsubscribe, manualRefresh } = useWebSocket({
    onKLineUpdate: handleKLineUpdate,
    onStatus: handleStatusMsg,
  })

  // ---- 手动刷新 ----
  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    manualRefresh()
    try {
      const resp = await fetch('/api/refresh', { method: 'POST' })
      await resp.text()
      await loadAllQuotes()
      if (currentSymbol) {
        // 刷新后以最大窗口 (30d) 拉取数据，同步切换预设
        setRangePreset('30d')
        await loadKLineByRange(currentSymbol, '30d')
      }
      // 同步刷新主力合约列表（可能已换月）
      getDominantSymbols().then(syms => {
        if (syms.length > 0) setSymbols(syms)
      })
      await loadStatus()
    } catch { /* ignore */ }
    setTimeout(() => setRefreshing(false), 800)
  }, [manualRefresh, currentSymbol, loadKLineByRange])

  // ---- 订阅 ----
  useEffect(() => {
    if (connectionStatus === 'connected' && selectedSymbols.length > 0) {
      subscribe(selectedSymbols)
    }
  }, [connectionStatus, selectedSymbols, subscribe])

  // ---- 定期拉取报价 ----
  useEffect(() => {
    if (selectedSymbols.length === 0) return
    const timer = setInterval(() => loadAllQuotes(), 15000)
    return () => clearInterval(timer)
  }, [selectedSymbols])

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      background: '#0e0e24',
      color: '#ddd',
      fontFamily: '"Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif',
    }}>
      {/* ──── 顶栏 ──── */}
      <header style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 16px',
        background: '#12122a',
        borderBottom: '1px solid #2a2a4e',
        flexWrap: 'wrap' as const,
      }}>
        <h1 style={{ fontSize: 16, fontWeight: 600, margin: 0, color: '#eee', whiteSpace: 'nowrap' }}>
          期货行情终端
        </h1>
        <SymbolSelector
          symbols={symbols}
          selected={selectedSymbols}
          onChange={handleSymbolsChange}
        />

        {/* 时间范围选择器 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginLeft: 8 }}>
          {RANGE_OPTIONS.map(opt => (
            <button
              key={opt.preset}
              onClick={() => handleRangeChange(opt.preset)}
              style={{
                padding: '3px 10px',
                fontSize: 12,
                border: '1px solid',
                borderColor: rangePreset === opt.preset ? '#6a6aae' : '#2a2a4e',
                borderRadius: 3,
                background: rangePreset === opt.preset ? '#2a2a5e' : 'transparent',
                color: rangePreset === opt.preset ? '#ddd' : '#777',
                cursor: 'pointer',
              }}
            >{opt.label}</button>
          ))}

          <span style={{ color: '#444', margin: '0 2px' }}>|</span>

          {/* 自定义按钮 + 输入 */}
          {rangePreset === 'custom' ? (
            <>
              <input
                type="datetime-local"
                value={customStart}
                onChange={e => setCustomStart(e.target.value)}
                style={{
                  padding: '2px 4px',
                  fontSize: 11,
                  background: '#1a1a3e',
                  border: '1px solid #2a2a4e',
                  borderRadius: 3,
                  color: '#aaa',
                  width: 160,
                }}
              />
              <span style={{ color: '#555' }}>~</span>
              <input
                type="datetime-local"
                value={customEnd}
                onChange={e => setCustomEnd(e.target.value)}
                style={{
                  padding: '2px 4px',
                  fontSize: 11,
                  background: '#1a1a3e',
                  border: '1px solid #2a2a4e',
                  borderRadius: 3,
                  color: '#aaa',
                  width: 160,
                }}
              />
              <button
                onClick={handleCustomRange}
                style={{
                  padding: '3px 10px',
                  fontSize: 12,
                  border: '1px solid #6a6aae',
                  borderRadius: 3,
                  background: '#2a2a5e',
                  color: '#ddd',
                  cursor: 'pointer',
                }}
              >查询</button>
            </>
          ) : (
            <button
              onClick={() => { setRangePreset('custom') }}
              style={{
                padding: '3px 10px',
                fontSize: 12,
                border: '1px solid #2a2a4e',
                borderRadius: 3,
                background: 'transparent',
                color: '#777',
                cursor: 'pointer',
              }}
            >自定义</button>
          )}
        </div>
      </header>

      {/* ──── 状态栏 + Loading ──── */}
      <StatusBar
        connectionStatus={connectionStatus}
        lastUpdate={lastUpdate}
        symbolCount={selectedSymbols.length}
        onRefresh={handleRefresh}
        refreshing={refreshing || loading}
      />

      {/* ──── 主区域 ──── */}
      <div style={{
        flex: 1,
        display: 'flex',
        overflow: 'hidden',
      }}>
        {/* K线图区域 */}
        <div style={{
          flex: 1,
          padding: 8,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
        }}>
          {currentSymbol ? (
            <>
              <div style={{
                fontSize: 13,
                color: '#888',
                marginBottom: 4,
                paddingLeft: 4,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span>{currentSymbol}</span>
                {kLinePeriod !== '1m' && (
                  <span style={{
                    fontSize: 11,
                    background: '#1a1a3e',
                    border: '1px solid #2a2a4e',
                    borderRadius: 3,
                    padding: '0 6px',
                    color: '#6a6aae',
                  }}>
                    {kLinePeriod}
                  </span>
                )}
                {loading && <span style={{ fontSize: 11, color: '#6a6aae' }}>加载中...</span>}
              </div>
              <div style={{ flex: 1, minHeight: 0 }}>
                <KLineChart symbol={currentSymbol} bars={kLineData} period={kLinePeriod} />
              </div>
            </>
          ) : (
            <div style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#555',
            }}>
              请选择一个品种
            </div>
          )}
        </div>

        {/* 报价表格（右侧栏） */}
        <div style={{
          width: 320,
          borderLeft: '1px solid #2a2a4e',
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{
            padding: '6px 10px',
            fontSize: 13,
            fontWeight: 600,
            color: '#aaa',
            borderBottom: '1px solid #2a2a4e',
          }}>
            实时报价
          </div>
          <div style={{ flex: 1, overflow: 'auto' }}>
            <QuoteTable
              quotes={quotes}
              symbols={symbols.filter(s => selectedSymbols.includes(s.full_symbol))}
              selectedSymbol={currentSymbol}
              onSelectSymbol={handleSelectSymbol}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
