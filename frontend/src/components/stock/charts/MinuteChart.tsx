import React, { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import type { MinuteData } from '../../../services/api';

interface MinuteChartProps {
  data: MinuteData[];
  stockCode?: string;
  stockName?: string;
  height?: number;
  prevClose?: number;
}

/**
 * 分时图组件
 * 显示股票的分钟级别价格走势和成交量
 * 采用中国股市习惯：红涨绿跌
 */
export const MinuteChart: React.FC<MinuteChartProps> = ({
  data,
  stockCode,
  stockName,
  height = 400,
  prevClose,
}) => {
  const chartOption: EChartsOption = useMemo(() => {
    if (data.length === 0) {
      return {};
    }

    // 生成完整的交易时段时间轴（9:30-15:00，去除11:30-13:00午休）
    const generateFullTimeAxis = () => {
      const times: string[] = [];

      // 上午时段：9:30-11:30 (120分钟)
      for (let h = 9; h <= 11; h++) {
        const startMin = h === 9 ? 30 : 0;
        const endMin = h === 11 ? 30 : 59;
        for (let m = startMin; m <= endMin; m++) {
          times.push(`${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`);
        }
      }

      // 下午时段：13:00-15:00 (120分钟)
      for (let h = 13; h <= 15; h++) {
        const startMin = 0;
        const endMin = h === 15 ? 0 : 59;
        for (let m = startMin; m <= endMin; m++) {
          times.push(`${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`);
        }
      }

      return times;
    };

    const fullTimeAxis = generateFullTimeAxis();

    // 创建时间到数据的映射
    const dataMap = new Map<string, MinuteData>();
    data.forEach((d) => {
      const timeParts = d.time.split(' ');
      if (timeParts.length > 1) {
        const hhmm = timeParts[1].substring(0, 5);
        dataMap.set(hhmm, d);
      }
    });

    // 计算昨收价（用于绘制基准线）
    const basePrice = prevClose || data[0]?.open || 0;

    // 填充完整时间轴的数据（未来时间用null填充）
    const prices: (number | null)[] = [];
    const avgPrices: (number | null)[] = [];
    const volumes: (number | null)[] = [];

    fullTimeAxis.forEach((time) => {
      const minuteData = dataMap.get(time);
      if (minuteData) {
        prices.push(minuteData.close);
        avgPrices.push(minuteData.avg_price);
        volumes.push(minuteData.volume);
      } else {
        prices.push(null);
        avgPrices.push(null);
        volumes.push(null);
      }
    });

    // 计算价格范围（以昨收为中心对称）
    const validPrices = prices.filter((p): p is number => p !== null);
    const validAvgPrices = avgPrices.filter((p): p is number => p !== null);
    const allPrices = [...validPrices, ...validAvgPrices, basePrice];
    const minPrice = Math.min(...allPrices);
    const maxPrice = Math.max(...allPrices);
    const maxDiff = Math.max(Math.abs(maxPrice - basePrice), Math.abs(basePrice - minPrice));
    const yMin = basePrice - maxDiff * 1.05;
    const yMax = basePrice + maxDiff * 1.05;

    // 成交量数据（根据涨跌着色）
    const volumeData = volumes.map((vol, idx) => {
      if (vol === null) {
        return { value: null };
      }
      const price = prices[idx];
      const isUp = price !== null && price >= basePrice;
      return {
        value: vol,
        itemStyle: {
          color: isUp ? '#FF3B30' : '#34C759',
          opacity: 0.7,
        },
      };
    });

    return {
      animation: true,
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
          crossStyle: {
            color: '#999',
          },
          lineStyle: {
            color: 'rgba(0, 0, 0, 0.2)',
            type: 'dashed',
          },
        },
        backgroundColor: 'rgba(255, 255, 255, 0.95)',
        borderColor: 'rgba(0, 0, 0, 0.1)',
        borderWidth: 1,
        textStyle: {
          color: '#1C1C1E',
          fontSize: 12,
        },
        formatter: (params: unknown) => {
          const paramArray = params as Array<{
            axisValue: string;
            data: number | null | { value: number | null };
            seriesName: string;
            dataIndex: number;
          }>;
          if (!paramArray || paramArray.length === 0) return '';

          const time = paramArray[0].axisValue;
          const dataIndex = paramArray[0].dataIndex;

          // 检查该时间点是否有数据
          const price = prices[dataIndex];
          if (price === null) {
            return `<div style="padding: 8px 12px;">
              <div style="color: #666; font-size: 11px; margin-bottom: 8px; font-weight: 600;">${time}</div>
              <div style="color: #999; font-size: 12px;">暂无数据</div>
            </div>`;
          }

          let html = `<div style="padding: 8px 12px;">
            <div style="color: #666; font-size: 11px; margin-bottom: 8px; font-weight: 600;">${time}</div>`;

          const avgPrice = avgPrices[dataIndex];
          const volume = volumes[dataIndex];
          const change = price - basePrice;
          const changePercent = basePrice > 0 ? ((change / basePrice) * 100).toFixed(2) : '0.00';
          const changeColor = change >= 0 ? '#FF3B30' : '#34C759';

          html += `
            <div style="display: grid; grid-template-columns: 60px 1fr; gap: 4px; font-size: 12px;">
              <span style="color: #999;">价格</span><span style="font-weight: 500; color: ${changeColor};">¥${price.toFixed(2)}</span>
              <span style="color: #999;">均价</span><span style="font-weight: 500;">¥${avgPrice?.toFixed(2) || '-'}</span>
              <span style="color: #999;">涨跌</span><span style="font-weight: 500; color: ${changeColor};">${change >= 0 ? '+' : ''}${change.toFixed(2)} (${change >= 0 ? '+' : ''}${changePercent}%)</span>
              <span style="color: #999;">成交量</span><span style="font-weight: 500;">${volume ? formatVolume(volume) : '-'}</span>
            </div>`;

          html += '</div>';
          return html;
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
        label: {
          backgroundColor: '#1C1C1E',
        },
      },
      grid: [
        {
          left: '10%',
          right: '8%',
          top: '8%',
          height: '60%',
        },
        {
          left: '10%',
          right: '8%',
          top: '75%',
          height: '15%',
        },
      ],
      xAxis: [
        {
          type: 'category',
          data: fullTimeAxis,
          boundaryGap: false,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            show: false,
          },
          splitLine: { show: false },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: fullTimeAxis,
          boundaryGap: false,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: '#9CA3AF',
            fontSize: 10,
            interval: (index: number) => {
              // 显示关键时间点：9:30, 10:30, 11:30/13:00, 14:00, 15:00
              const time = fullTimeAxis[index];
              return time === '09:30' || time === '10:30' || time === '11:30' ||
                     time === '13:00' || time === '14:00' || time === '15:00';
            },
          },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          scale: false,
          min: yMin,
          max: yMax,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: '#9CA3AF',
            fontSize: 10,
            formatter: (value: number) => {
              const change = value - basePrice;
              const changePercent = basePrice > 0 ? ((change / basePrice) * 100).toFixed(1) : '0.0';
              return `${value.toFixed(2)}\n${change >= 0 ? '+' : ''}${changePercent}%`;
            },
          },
          splitLine: {
            lineStyle: {
              color: 'rgba(0, 0, 0, 0.05)',
              type: 'dashed',
            },
          },
        },
        {
          type: 'value',
          gridIndex: 1,
          scale: true,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: '#9CA3AF',
            fontSize: 10,
            formatter: (value: number) => {
              if (value >= 100000000) return `${(value / 100000000).toFixed(1)}亿`;
              if (value >= 10000) return `${(value / 10000).toFixed(0)}万`;
              return value.toString();
            },
          },
          splitLine: {
            lineStyle: {
              color: 'rgba(0, 0, 0, 0.05)',
              type: 'dashed',
            },
          },
        },
      ],
      series: [
        {
          name: '价格',
          type: 'line',
          data: prices,
          smooth: false,
          symbol: 'none',
          lineStyle: {
            color: '#007AFF',
            width: 1.5,
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(0, 122, 255, 0.2)' },
                { offset: 1, color: 'rgba(0, 122, 255, 0.02)' },
              ],
            },
          },
          connectNulls: false, // 不连接null值
        },
        {
          name: '均价',
          type: 'line',
          data: avgPrices,
          smooth: false,
          symbol: 'none',
          lineStyle: {
            color: '#FF9500',
            width: 1,
            type: 'solid',
          },
          connectNulls: false,
        },
        {
          name: '昨收',
          type: 'line',
          data: Array(fullTimeAxis.length).fill(basePrice),
          symbol: 'none',
          lineStyle: {
            color: '#999',
            width: 1,
            type: 'dashed',
          },
          silent: true,
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumeData,
          barWidth: '80%',
        },
      ],
    };
  }, [data, prevClose]);

  // 计算统计数据
  const stats = useMemo(() => {
    if (data.length === 0) return null;

    const lastData = data[data.length - 1];
    const basePrice = prevClose || data[0]?.open || 0;
    const change = lastData.close - basePrice;
    const changePercent = basePrice > 0 ? (change / basePrice) * 100 : 0;

    const highestPrice = Math.max(...data.map((d) => d.high));
    const lowestPrice = Math.min(...data.map((d) => d.low));

    const totalVolume = data.reduce((sum, d) => sum + d.volume, 0);
    const totalAmount = data.reduce((sum, d) => sum + d.amount, 0);

    return {
      currentPrice: lastData.close,
      avgPrice: lastData.avg_price,
      change,
      changePercent,
      highestPrice,
      lowestPrice,
      totalVolume,
      totalAmount,
      basePrice,
    };
  }, [data, prevClose]);

  const formatVolume = (value: number): string => {
    if (value >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
    if (value >= 10000) return `${(value / 10000).toFixed(2)}万`;
    return value.toString();
  };

  const formatAmount = (value: number): string => {
    if (value >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
    if (value >= 10000) return `${(value / 10000).toFixed(2)}万`;
    return value.toFixed(2);
  };

  return (
    <div>
      {/* 头部信息 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-600">
            {stockCode && stockName ? `${stockCode} ${stockName}` : stockCode || '分时图'}
          </span>
          {stats && (
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-space-black">
                ¥{stats.currentPrice.toFixed(2)}
              </span>
              <span
                className={`text-xs font-medium ${stats.changePercent >= 0 ? 'text-profit-green' : 'text-loss-red'}`}
              >
                {stats.changePercent >= 0 ? '+' : ''}
                {stats.change.toFixed(2)} ({stats.changePercent >= 0 ? '+' : ''}
                {stats.changePercent.toFixed(2)}%)
              </span>
            </div>
          )}
        </div>
        {stats && (
          <div className="flex items-center gap-4 text-xs text-gray-400">
            <span>
              最高: <span className="text-profit-green">¥{stats.highestPrice.toFixed(2)}</span>
            </span>
            <span>
              最低: <span className="text-loss-red">¥{stats.lowestPrice.toFixed(2)}</span>
            </span>
            <span>
              均价: <span className="text-gray-600">¥{stats.avgPrice.toFixed(2)}</span>
            </span>
            <span>
              成交量: <span className="text-gray-600">{formatVolume(stats.totalVolume)}</span>
            </span>
          </div>
        )}
      </div>

      {/* 图表 */}
      {data.length === 0 ? (
        <div
          className="flex items-center justify-center text-gray-400"
          style={{ height }}
        >
          暂无分时数据
        </div>
      ) : (
        <ReactECharts
          option={chartOption}
          style={{ height, width: '100%' }}
          opts={{ renderer: 'svg' }}
        />
      )}
    </div>
  );
};

export default MinuteChart;
