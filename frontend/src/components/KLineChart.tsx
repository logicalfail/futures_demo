/**
 * K线图表组件
 * - ECharts candlestick + 成交量
 * - 自适应容器
 * - 空数据友好展示
 */

import React, { useMemo } from 'react'
import ReactEChartsCore from 'echarts-for-react'
import type { KLineData } from '../types'

interface Props {
  symbol: string
  bars: KLineData[]
}

const COLORS = {
  up: '#ef5350',
  down: '#26a69a',
  volume: 'rgba(128,128,128,0.3)',
  volumeUp: 'rgba(239,83,80,0.4)',
  volumeDown: 'rgba(38,166,154,0.4)',
}

export default function KLineChart({ symbol, bars }: Props) {
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

    // 按时间升序排列
    const sorted = [...bars].sort((a, b) => a.ts_ns - b.ts_ns)
    const categories = sorted.map(b => b.ts.slice(11, 16)) // HH:mm
    const ohlc = sorted.map(b => [b.open, b.close, b.low, b.high])
    const volumes = sorted.map(b => b.volume)
    const upColors = sorted.map(b => b.close >= b.open)

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any[]) => {
          if (!params || params.length === 0) return ''
          const bar = sorted[params[0].dataIndex]
          if (!bar) return ''
          return `
            <b>${bar.ts}</b><br/>
            开盘: ${bar.open.toFixed(2)}<br/>
            最高: ${bar.high.toFixed(2)}<br/>
            最低: ${bar.low.toFixed(2)}<br/>
            收盘: ${bar.close.toFixed(2)}<br/>
            成交量: ${bar.volume.toLocaleString()}
          `
        },
      },
      legend: { show: false },
      grid: [
        { left: '8%', right: '3%', top: '8%', height: '62%' },
        { left: '8%', right: '3%', top: '78%', height: '15%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: categories,
          axisLine: { onZero: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { fontSize: 10, rotate: 45 },
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
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, height: 12, bottom: 2 },
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
    <div style={{ width: '100%', height: '100%', minHeight: 400 }}>
      <ReactEChartsCore
        option={option}
        style={{ height: '100%', minHeight: 400 }}
        notMerge
        lazyUpdate
      />
    </div>
  )
}
