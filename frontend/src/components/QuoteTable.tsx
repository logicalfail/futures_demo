/**
 * 实时报价表格
 * - 显示所有订阅品种的最新价/涨跌幅/成交量/持仓量
 * - 涨红跌绿
 */

import React from 'react'
import type { KLineData, SymbolInfo } from '../types'

interface Props {
  quotes: Map<string, KLineData>
  symbols: SymbolInfo[]
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
}

function fmt(v: number | undefined | null, decimals = 2): string {
  if (v === undefined || v === null) return '--'
  return v.toFixed(decimals)
}

function pct(a: number | undefined | null, b: number | undefined | null): number | null {
  if (a == null || b == null || b === 0) return null
  return ((a - b) / b) * 100
}

export default function QuoteTable({
  quotes, symbols, selectedSymbol, onSelectSymbol,
}: Props) {
  // 按品种代码排序展示
  const rows = symbols.map(sym => {
    const quote = quotes.get(sym.full_symbol)
    const prevClose = quote?.open ?? null  // 用开盘价作为替代
    const changePct = pct(quote?.close, prevClose)
    const isPositive = changePct !== null && changePct >= 0

    return {
      ...sym,
      quote,
      changePct,
      isPositive,
    }
  })

  return (
    <div style={{ overflow: 'auto', maxHeight: '100%' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ position: 'sticky', top: 0, background: '#1a1a2e', color: '#aaa' }}>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>品种</th>
            <th style={{ padding: '6px 8px', textAlign: 'right' }}>最新价</th>
            <th style={{ padding: '6px 8px', textAlign: 'right' }}>涨跌幅</th>
            <th style={{ padding: '6px 8px', textAlign: 'right' }}>成交量</th>
            <th style={{ padding: '6px 8px', textAlign: 'right' }}>持仓量</th>
            <th style={{ padding: '6px 8px', textAlign: 'right' }}>时间</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const isSelected = row.full_symbol === selectedSymbol
            return (
              <tr
                key={row.full_symbol}
                onClick={() => onSelectSymbol(row.full_symbol)}
                style={{
                  cursor: 'pointer',
                  background: isSelected ? '#2a2a4e' : undefined,
                  borderBottom: '1px solid #2a2a3e',
                }}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = '#222240' }}
                onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = '' }}
              >
                <td style={{ padding: '5px 8px' }}>
                  <div>{row.code}</div>
                  <div style={{ fontSize: 11, color: '#888' }}>{row.exchange}</div>
                </td>
                <td style={{
                  padding: '5px 8px',
                  textAlign: 'right',
                  color: row.isPositive ? '#ef5350' : '#26a69a',
                  fontWeight: 'bold',
                }}>
                  {row.quote ? fmt(row.quote.close) : '--'}
                </td>
                <td style={{
                  padding: '5px 8px',
                  textAlign: 'right',
                  color: row.changePct !== null ? (row.isPositive ? '#ef5350' : '#26a69a') : '#888',
                }}>
                  {row.changePct !== null ? `${row.isPositive ? '+' : ''}${row.changePct.toFixed(2)}%` : '--'}
                </td>
                <td style={{ padding: '5px 8px', textAlign: 'right' }}>
                  {row.quote ? row.quote.volume.toLocaleString() : '--'}
                </td>
                <td style={{ padding: '5px 8px', textAlign: 'right' }}>
                  {row.quote?.open_interest != null ? row.quote.open_interest.toLocaleString() : '--'}
                </td>
                <td style={{ padding: '5px 8px', textAlign: 'right', fontSize: 11, color: '#aaa' }}>
                  {row.quote ? row.quote.ts.slice(11, 19) : '--'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
