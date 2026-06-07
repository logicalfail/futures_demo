/**
 * WebSocket Hook
 * - 自动连接/重连
 * - 订阅/取消订阅品种
 * - K线更新回调
 * - 连接状态管理
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import type { ConnectionStatus, WSMessage, KLineData } from '../types'

interface UseWebSocketOptions {
  onKLineUpdate?: (symbol: string, bars: KLineData[]) => void
  onStatus?: (status: string, message: string) => void
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

export function useWebSocket(options: UseWebSocketOptions) {
  const {
    onKLineUpdate,
    onStatus,
    reconnectInterval = 3000,
    maxReconnectAttempts = 20,
  } = options

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectCountRef = useRef(0)
  const reconnectTimerRef = useRef<number | null>(null)
  const mountedRef = useRef(true)

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected')
  const subscribedRef = useRef<Set<string>>(new Set())

  // ---- 发送消息 ----
  const send = useCallback((msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  // ---- 订阅品种 ----
  const subscribe = useCallback((symbols: string[]) => {
    symbols.forEach(s => subscribedRef.current.add(s))
    send({ type: 'subscribe', symbols })
  }, [send])

  // ---- 取消订阅 ----
  const unsubscribe = useCallback((symbols: string[]) => {
    symbols.forEach(s => subscribedRef.current.delete(s))
    send({ type: 'unsubscribe', symbols })
  }, [send])

  // ---- 手动刷新 ----
  const manualRefresh = useCallback(() => {
    send({ type: 'manual_refresh' })
  }, [send])

  // ---- 连接逻辑 ----
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    setConnectionStatus('connecting')
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const url = `${protocol}//${host}/ws`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnectionStatus('connected')
      reconnectCountRef.current = 0

      // 重新订阅之前订阅过的品种
      const symbols = Array.from(subscribedRef.current)
      if (symbols.length > 0) {
        ws.send(JSON.stringify({ type: 'subscribe', symbols }))
      }
    }

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)
        handleMessage(msg)
      } catch { /* ignore malformed */ }
    }

    ws.onerror = () => {
      setConnectionStatus('error')
    }

    ws.onclose = () => {
      setConnectionStatus('disconnected')
      wsRef.current = null
      // 自动重连
      if (mountedRef.current && reconnectCountRef.current < maxReconnectAttempts) {
        reconnectCountRef.current++
        reconnectTimerRef.current = window.setTimeout(connect, reconnectInterval)
      }
    }
  }, [reconnectInterval, maxReconnectAttempts])

  // ---- 消息分发 ----
  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'kline_update':
        onKLineUpdate?.(msg.symbol, msg.bars)
        break
      case 'status':
        onStatus?.(msg.status, msg.message)
        break
      case 'ping':
        send({ type: 'pong' })
        break
      case 'error':
        console.warn('[WS Error]', msg.message)
        break
    }
  }, [onKLineUpdate, onStatus, send])

  // ---- 生命周期 ----
  useEffect(() => {
    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [connect])

  return {
    connectionStatus,
    subscribe,
    unsubscribe,
    manualRefresh,
    send,
  }
}
