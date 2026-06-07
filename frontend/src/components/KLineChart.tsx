/**
 * K线图表组件
 * - ECharts candlestick + 成交量
 * - 鼠标滚轮缩放 / 拖拽平移
 * - 跨交易日日期标签
 * - 交易时段间隔标记
 */

import React, { useMemo } from 'react'
import ReactEChartsCore from 'echarts-for-react'
import type { KLineData, Period } from '../types'

interface Props {
  symbol: string
  bars: KLineData[]
  period?: Period       // 当前聚合周期，用于显示
}

const COLORS = {
  up: '#ef5350',
  down: '#26a69a',
  volume: 'rgba(128,128,128,0.3)',
  volumeUp: 'rgba(239,83,80,0.4)',
  volumeDown: 'rgba(38,166,154,0.4)',
}

function hasSessionGap(a: string, b: string): boolean {
  const t1 = new Date(a).getTime()
  const t2 = new Date(b).getTime()
  return (t2 - t1) > 30 * 60 * 1000
}

function datePart(ts: string): string {
  return ts.slice(0, 10)
}

function timePart(ts: string): string {
  return ts.slice(11, 16)
}

function fmtLabel(ts: string, showDate: boolean): string {
  if (showDate) {
    return datePart(ts).slice(5) + '\n' + timePart(ts)
  }
  return timePart(ts)
}

export default function KLineChart({ symbol, bars, period }: Props) {
  const option = useMemo(() => {
    if (!bars || bars.length === 0) {
      return {
        title: { text: symbol || 'K线图', left: 'center', textStyle: { fontSize: 14 } },
        xAxis: { type: 'category', data: [] },
        yAxis: { type: 'value' },
        series: [{ type: 'candlestick', data: [] }],
        grid: { bottom: '20%' },
      }
    }

    const sorted = [...bars].sort((a, b) => a.ts_ns - b.ts_ns)
    const multiDay = sorted.length > 1 &&
      datePart(sorted[0].ts) !== datePart(sorted[sorted.length - 1].ts)

    const categories = sorted.map((b, i) => {
      if (!multiDay) return timePart(b.ts)
      const prevDate = i === 0 ? '' : datePart(sorted[i - 1].ts)
      return fmtLabel(b.ts, datePart(b.ts) !== prevDate)
    })

    const ohlc = sorted.map(b => [b.open, b.close, b.low, b.high])
    const volumes = sorted.map(b => b.volume)
    const upColors = sorted.map(b => b.close >= b.open)

    const markLineData: any[] = []
    if (multiDay) {
      for (let i = 1; i < sorted.length; i++) {
        if (hasSessionGap(sorted[i - 1].ts, sorted[i].ts)) {
          markLineData.push({ xAxis: i - 0.5 })
        }
      }
    }

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any[]) => {
          if (!params || params.length === 0) return ''
          const bar = sorted[params[0].dataIndex]
          if (!bar) return ''
          const oi = bar.open_interest != null ? ` | 持仓: ${bar.open_interest.toLocaleString()}` : ''
          return `
            <b>${bar.ts}</b><br/>
            O:${bar.open.toFixed(2)} / H:${bar.high.toFixed(2)} / L:${bar.low.toFixed(2)} / C:${bar.close.toFixed(2)}<br/>
            成交量: ${bar.volume.toLocaleString()}${oi}
          `
        },
      },
      legend: { show: false },
      grid: [
        { left: '8%', right: '3%', top: '6%', height: '64%' },
        { left: '8%', right: '3%', top: '78%', height: '14%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: categories,
          axisLine: { onZero: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: {
            fontSize: 10,
            rotate: multiDay ? 0 : 45,
            interval: multiDay ? (idx: number) => categories[idx].includes('\n') : 'auto',
            align: 'center',
            lineHeight: 14,
          },
          gridIndex: 0,
        },
        {
          type: 'category',
          data: categories,
          axisLine: { onZero: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          gridIndex: 1,
        },
      ],
      yAxis: [
        {
          type: 'value',
          scale: true,
          splitNumber: 5,
          axisLabel: { fontSize: 10 },
          gridIndex: 0,
        },
        {
          type: 'value',
          scale: true,
          splitNumber: 3,
          axisLabel: { fontSize: 10 },
          gridIndex: 1,
        },
      ],
      // ── 数据缩放：鼠标滚轮缩放 + 拖拽平移 ──
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 0,
          end: 100,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,      // 鼠标拖拽平移
          moveOnMouseWheel: false,    // 滚轮仅缩放，不触发平移
        },
        {
          type: 'slider',
          xAxisIndex: [0, 1],
          start: 0,
          end: 100,
          height: 14,
          bottom: 4,
          borderColor: '#2a2a4e',
          backgroundColor: '#1a1a3e',
          dataBackground: {
            lineStyle: { color: '#4a4a7e' },
            areaStyle: { color: '#2a2a4e' },
          },
          selectedDataBackground: {
            lineStyle: { color: '#6a6aae' },
            areaStyle: { color: '#3a3a6e' },
          },
          handleStyle: { color: '#6a6aae', borderColor: '#6a6aae' },
          textStyle: { color: '#999', fontSize: 10 },
        },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          itemStyle: {
            color: COLORS.up,
            color0: COLORS.down,
            borderColor: COLORS.up,
            borderColor0: COLORS.down,
          },
          ...(markLineData.length > 0 ? {
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { color: '#3a3a5e', type: 'dashed', width: 1 },
              data: markLineData,
              label: { show: false },
            },
          } : {}),
        },
        {
          name: '成交量',
          type: 'bar',
          data: volumes.map((v, i) => ({
            value: v,
            itemStyle: {
              color: upColors[i] ? COLORS.volumeUp : COLORS.volumeDown,
            },
          })),
          xAxisIndex: 1,
          yAxisIndex: 1,
        },
      ],
      animation: false,
    }
  }, [bars, symbol])

  return (
    <div style={{ width: '100%', height: '100%', minHeight: 400, position: 'relative' }}>
      {/* 顶部信息：品种名 + 周期 + 操作提示 */}
      <div style={{
        position: 'absolute',
        top: 4,
        left: 8,
        zIndex: 10,
        fontSize: 12,
        color: '#666',
        pointerEvents: 'none',
      }}>
        {period && period !== '1m' ? `${period}` : ''}
      </div>
      <div style={{
        position: 'absolute',
        bottom: 32,
        right: 8,
        zIndex: 10,
        fontSize: 11,
        color: '#444',
        pointerEvents: 'none',
      }}>
        滚轮缩放 · 拖动平移
      </div>
      <ReactEChartsCore
        option={option}
        style={{ height: '100%', minHeight: 400 }}
        notMerge
        lazyUpdate
      />
    </div>
  )
}
