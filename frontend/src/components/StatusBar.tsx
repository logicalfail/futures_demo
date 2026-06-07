/**
 * 状态栏
 * - 连接状态指示灯
 * - 最后更新时间
 * - 品种数量
 * - 手动刷新按钮
 */

import React from 'react'
import type { ConnectionStatus } from '../types'

interface Props {
  connectionStatus: ConnectionStatus
  lastUpdate: string
  symbolCount: number
  onRefresh: () => void
  refreshing: boolean
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: '已连接',
  connecting: '连接中...',
  disconnected: '未连接',
  error: '连接错误',
}

const STATUS_COLOR: Record<ConnectionStatus, string> = {
  connected: '#4caf50',
  connecting: '#ff9800',
  disconnected: '#f44336',
  error: '#f44336',
}

export default function StatusBar({
  connectionStatus, lastUpdate, symbolCount, onRefresh, refreshing,
}: Props) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      padding: '6px 16px',
      background: '#12122a',
      borderBottom: '1px solid #2a2a4e',
      fontSize: 13,
      color: '#aaa',
      flexWrap: 'wrap',
    }}>
      {/* 连接状态 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: STATUS_COLOR[connectionStatus],
          display: 'inline-block',
        }} />
        <span>{STATUS_LABEL[connectionStatus]}</span>
      </div>

      {/* 分隔线 */}
      <span style={{ color: '#3a3a5e' }}>|</span>

      {/* 品种数 */}
      <span>品种: {symbolCount}</span>

      <span style={{ color: '#3a3a5e' }}>|</span>

      {/* 最后更新 */}
      <span>更新: {lastUpdate || '--'}</span>

      {/* 刷新按钮 */}
      <button
        onClick={onRefresh}
        disabled={refreshing}
        style={{
          marginLeft: 'auto',
          padding: '4px 14px',
          background: refreshing ? '#3a3a5e' : '#2a2a5e',
          border: '1px solid #4a4a7e',
          borderRadius: 4,
          color: refreshing ? '#888' : '#ddd',
          cursor: refreshing ? 'not-allowed' : 'pointer',
          fontSize: 12,
        }}
      >
        {refreshing ? '刷新中...' : '手动刷新'}
      </button>
    </div>
  )
}
