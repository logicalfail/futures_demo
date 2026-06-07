/**
 * 期货行情终端 - 主应用
 * - K线图（中央）
 * - 报价表格（右侧）
 * - 品种选择器（上方/工具栏）
 * - 状态栏（底部）
 */

import React, { useEffect, useState, useCallback, useRef } from 'react'
import KLineChart from './components/KLineChart'
import QuoteTable from './components/QuoteTable'
import SymbolSelector from './components/SymbolSelector'
import StatusBar from './components/StatusBar'
import { useWebSocket } from './hooks/useWebSocket'
import { getSymbols, getKLine, getStatus, getQuote } from './api/dataService'
import type { SymbolInfo, KLineData } from './types'

export default function App() {
  // ---- 品种数据 ----
  const [symbols, setSymbols] = useState<SymbolInfo[]>([])
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [currentSymbol, setCurrentSymbol] = useState<string | null>(null)
  const [kLineData, setKLineData] = useState<KLineData[]>([])
  const [quotes, setQuotes] = useState<Map<string, KLineData>>(new Map())
  const [lastUpdate, setLastUpdate] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  // ---- 初始化 ----
  useEffect(() => {
    getSymbols().then(syms => {
      setSymbols(syms)
      if (syms.length > 0) {
        // 默认选中第一个品种
        const first = syms[0].full_symbol
        setSelectedSymbols([first])
        setCurrentSymbol(first)
        loadKLine(first)
        loadQuote(first)
      }
    })
    loadStatus()
  }, [])

  // ---- 数据加载 ----
  const loadKLine = async (symbol: string) => {
    try {
      const bars = await getKLine(symbol, 300, 3)
      setKLineData(bars)
    } catch (e) {
      console.warn('Failed to load KLine:', e)
    }
  }

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
    loadKLine(symbol)
  }, [])

  // ---- 品种选择变更 ----
  const handleSymbolsChange = useCallback((selected: string[]) => {
    setSelectedSymbols(selected)
    // 如果当前品种被取消，切换到第一个
    if (currentSymbol && !selected.includes(currentSymbol) && selected.length > 0) {
      setCurrentSymbol(selected[0])
      loadKLine(selected[0])
    }
    if (selected.length === 0) {
      setCurrentSymbol(null)
      setKLineData([])
    }
  }, [currentSymbol])

  // ---- WebSocket 回调 ----
  const handleKLineUpdate = useCallback((symbol: string, bars: KLineData[]) => {
    if (symbol === currentSymbol) {
      setKLineData(prev => {
        // 合并更新：用新bars替换旧数据
        const existing = new Map(prev.map(b => [b.ts_ns, b]))
        for (const bar of bars) existing.set(bar.ts_ns, bar)
        return Array.from(existing.values()).sort((a, b) => a.ts_ns - b.ts_ns)
      })
    }
    // 更新报价表
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

  // ---- WebSocket 连接 ----
  const { connectionStatus, subscribe, unsubscribe, manualRefresh } = useWebSocket({
    onKLineUpdate: handleKLineUpdate,
    onStatus: handleStatusMsg,
  })

  // ---- 手动刷新 ----
  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    manualRefresh()
    // 也通过 HTTP 刷新一次
    try {
      const resp = await fetch('/api/refresh', { method: 'POST' })
      await resp.text()
      await loadAllQuotes()
      if (currentSymbol) await loadKLine(currentSymbol)
      await loadStatus()
    } catch { /* ignore */ }
    setTimeout(() => setRefreshing(false), 800)
  }, [manualRefresh, currentSymbol])

  // ---- 品种选择变化时重新订阅 ----
  useEffect(() => {
    // WS 连接建立后自动订阅
    if (connectionStatus === 'connected' && selectedSymbols.length > 0) {
      subscribe(selectedSymbols)
    }
  }, [connectionStatus, selectedSymbols, subscribe])

  // ---- 定期拉取报价（兜底，防止WS丢数据） ----
  useEffect(() => {
    if (selectedSymbols.length === 0) return
    const timer = setInterval(() => {
      loadAllQuotes()
    }, 15000) // 每15秒拉一次
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
      {/* ---- 顶栏 ---- */}
      <header style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 16px',
        background: '#12122a',
        borderBottom: '1px solid #2a2a4e',
      }}>
        <h1 style={{ fontSize: 16, fontWeight: 600, margin: 0, color: '#eee' }}>
          期货行情终端
        </h1>
        <div style={{ flex: 1 }} />
        <SymbolSelector
          symbols={symbols}
          selected={selectedSymbols}
          onChange={handleSymbolsChange}
        />
      </header>

      {/* ---- 状态栏 ---- */}
      <StatusBar
        connectionStatus={connectionStatus}
        lastUpdate={lastUpdate}
        symbolCount={selectedSymbols.length}
        onRefresh={handleRefresh}
        refreshing={refreshing}
      />

      {/* ---- 主区域 ---- */}
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
              <div style={{ fontSize: 13, color: '#888', marginBottom: 4, paddingLeft: 4 }}>
                {currentSymbol}
              </div>
              <div style={{ flex: 1, minHeight: 0 }}>
                <KLineChart symbol={currentSymbol} bars={kLineData} />
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
