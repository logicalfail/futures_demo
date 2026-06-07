/**
 * 品种选择器
 * - 下拉多选框
 * - 显示品种代码 + 交易所
 */

import React, { useState, useRef, useEffect } from 'react'
import type { SymbolInfo } from '../types'

interface Props {
  symbols: SymbolInfo[]
  selected: string[]
  onChange: (selected: string[]) => void
}

export default function SymbolSelector({ symbols, selected, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // 点击外部关闭
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const toggle = (fullSymbol: string) => {
    const next = selected.includes(fullSymbol)
      ? selected.filter(s => s !== fullSymbol)
      : [...selected, fullSymbol]
    onChange(next)
  }

  const selectAll = () => onChange(symbols.map(s => s.full_symbol))
  const clearAll = () => onChange([])

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {/* 触发器 */}
      <div
        onClick={() => setOpen(!open)}
        style={{
          padding: '6px 12px',
          background: '#1e1e3a',
          border: '1px solid #3a3a5e',
          borderRadius: 4,
          cursor: 'pointer',
          minWidth: 200,
          color: '#eee',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: 13,
        }}
      >
        <span>{selected.length === 0 ? '选择品种...' : `已选 ${selected.length} 个`}</span>
        <span style={{ fontSize: 10 }}>{open ? '▲' : '▼'}</span>
      </div>

      {/* 下拉面板 */}
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 100,
            background: '#1a1a2e',
            border: '1px solid #3a3a5e',
            borderRadius: 4,
            marginTop: 2,
            maxHeight: 300,
            overflow: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          {/* 全选/清空 */}
          <div style={{ padding: '6px 8px', borderBottom: '1px solid #3a3a5e', display: 'flex', gap: 8 }}>
            <button onClick={selectAll} style={btnStyle}>全选</button>
            <button onClick={clearAll} style={btnStyle}>清空</button>
          </div>
          {/* 品种列表 */}
          {symbols.map(sym => (
            <label
              key={sym.full_symbol}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '5px 8px',
                cursor: 'pointer',
                fontSize: 13,
              }}
            >
              <input
                type="checkbox"
                checked={selected.includes(sym.full_symbol)}
                onChange={() => toggle(sym.full_symbol)}
                style={{ marginRight: 8 }}
              />
              <span style={{ flex: 1 }}>{sym.code}</span>
              <span style={{ color: '#888', fontSize: 11 }}>{sym.exchange}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

const btnStyle: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid #4a4a6e',
  color: '#ccc',
  borderRadius: 3,
  padding: '2px 10px',
  cursor: 'pointer',
  fontSize: 12,
}
