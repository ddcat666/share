import React, { useEffect, useState, useCallback } from 'react';
import { stockApi, type MinuteData, type StockRealtimeQuote } from '../../../services/api';
import { MinuteChart } from '../charts/MinuteChart';
import { GlassCard } from '../../ui';

interface MinuteTabProps {
  stockCode: string;
}

/**
 * 分时图标签页
 * 显示股票的分钟级别价格走势（单日数据，支持实时刷新）
 */
export const MinuteTab: React.FC<MinuteTabProps> = ({ stockCode }) => {
  const [loading, setLoading] = useState(true);
  const [minuteData, setMinuteData] = useState<MinuteData[]>([]);
  const [quote, setQuote] = useState<StockRealtimeQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<'1' | '5' | '15' | '30' | '60'>('1');
  const [selectedDate, setSelectedDate] = useState<string>(''); // 选择的日期
  const [autoRefresh, setAutoRefresh] = useState(true); // 自动刷新开关

  // 获取今天的日期字符串 YYYY-MM-DD
  const getTodayString = () => {
    const today = new Date();
    return today.toISOString().split('T')[0];
  };

  // 初始化选择今天
  useEffect(() => {
    setSelectedDate(getTodayString());
  }, []);

  // 加载分时数据（只加载选定日期的数据）
  const loadMinuteData = useCallback(async (showLoading = true) => {
    if (!selectedDate) return;

    if (showLoading) {
      setLoading(true);
    }
    setError(null);

    try {
      // 设置开始和结束时间为选定日期的交易时段
      const startDateTime = `${selectedDate} 09:15:00`;
      const endDateTime = `${selectedDate} 15:30:00`;

      // 并行加载分时数据和实时行情
      const [minuteResponse, quoteResponse] = await Promise.all([
        stockApi.getMinuteData(stockCode, {
          period,
          start_date: startDateTime,
          end_date: endDateTime,
        }),
        stockApi.getQuote(stockCode),
      ]);

      // 过滤出选定日期的数据
      const filteredData = minuteResponse.data.filter(item =>
        item.time.startsWith(selectedDate)
      );

      setMinuteData(filteredData);
      setQuote(quoteResponse);
    } catch (err) {
      console.error('加载分时数据失败:', err);
      setError('加载分时数据失败，请稍后重试');
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, [stockCode, period, selectedDate]);

  // 初始加载
  useEffect(() => {
    if (selectedDate) {
      loadMinuteData();
    }
  }, [loadMinuteData, selectedDate]);

  // 自动刷新（仅当选择今天且开启自动刷新时）
  useEffect(() => {
    const isToday = selectedDate === getTodayString();
    if (!isToday || !autoRefresh) return;

    // 每30秒刷新一次分时数据
    const interval = setInterval(() => {
      loadMinuteData(false); // 后台刷新，不显示loading
    }, 30000);

    return () => clearInterval(interval);
  }, [selectedDate, autoRefresh, loadMinuteData]);

  // 周期选项
  const periodOptions: { value: '1' | '5' | '15' | '30' | '60'; label: string }[] = [
    { value: '1', label: '1分钟' },
    { value: '5', label: '5分钟' },
    { value: '15', label: '15分钟' },
    { value: '30', label: '30分钟' },
    { value: '60', label: '60分钟' },
  ];

  // 生成最近5个交易日的日期选项
  const getRecentTradingDays = () => {
    const days: string[] = [];
    const today = new Date();
    let count = 0;
    let offset = 0;

    while (count < 5) {
      const date = new Date(today);
      date.setDate(today.getDate() - offset);
      const dayOfWeek = date.getDay();

      // 跳过周末
      if (dayOfWeek !== 0 && dayOfWeek !== 6) {
        days.push(date.toISOString().split('T')[0]);
        count++;
      }
      offset++;
    }

    return days;
  };

  const tradingDays = getRecentTradingDays();
  const isToday = selectedDate === getTodayString();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64">
        <svg className="w-12 h-12 text-red-400 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <p className="text-gray-600 mb-4">{error}</p>
        <button
          onClick={() => loadMinuteData()}
          className="px-4 py-2 bg-space-black text-white rounded-lg text-sm hover:bg-gray-800 transition-colors"
        >
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 控制栏：日期选择 + 周期选择 + 自动刷新 */}
      <GlassCard className="p-4 rounded-[7px]">
        <div className="flex flex-col md:flex-row gap-4">
          {/* 日期选择 */}
          <div className="flex-1">
            <div className="text-xs text-gray-400 mb-2">交易日期</div>
            <div className="flex gap-2 flex-wrap">
              {tradingDays.map((date, index) => {
                const dateObj = new Date(date + 'T00:00:00');
                const label = index === 0 ? '今天' : `${dateObj.getMonth() + 1}月${dateObj.getDate()}日`;
                return (
                  <button
                    key={date}
                    onClick={() => setSelectedDate(date)}
                    className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                      selectedDate === date
                        ? 'bg-info-blue text-white'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 周期选择 */}
          <div className="flex-1">
            <div className="text-xs text-gray-400 mb-2">时间周期</div>
            <div className="flex gap-2 flex-wrap">
              {periodOptions.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setPeriod(option.value)}
                  className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                    period === option.value
                      ? 'bg-space-black text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          {/* 自动刷新开关（仅今天可用） */}
          {isToday && (
            <div className="flex items-end">
              <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg transition-colors ${
                  autoRefresh
                    ? 'bg-profit-green/10 text-profit-green'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
                title={autoRefresh ? '关闭自动刷新' : '开启自动刷新（每30秒）'}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {autoRefresh ? '实时刷新' : '手动刷新'}
              </button>
            </div>
          )}
        </div>
      </GlassCard>

      {/* 分时图 */}
      <GlassCard className="p-6 rounded-[7px]">
        <MinuteChart
          data={minuteData}
          stockCode={stockCode}
          stockName={quote?.price ? `当前价: ¥${quote.price.toFixed(2)}` : undefined}
          height={500}
          prevClose={quote?.prev_close}
        />
      </GlassCard>

      {/* 数据统计 */}
      {minuteData.length > 0 ? (
        <GlassCard className="p-4 rounded-[7px]">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <div className="text-xs text-gray-400 mb-1">交易日期</div>
              <div className="text-sm font-medium text-space-black">
                {(() => {
                  const dateObj = new Date(selectedDate + 'T00:00:00');
                  return `${dateObj.getMonth() + 1}月${dateObj.getDate()}日`;
                })()}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-1">数据点数</div>
              <div className="text-sm font-medium text-space-black">{minuteData.length} 条</div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-1">时间范围</div>
              <div className="text-sm font-medium text-space-black">
                {minuteData[0]?.time.split(' ')[1]?.substring(0, 5)} - {minuteData[minuteData.length - 1]?.time.split(' ')[1]?.substring(0, 5)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-1">最新价</div>
              <div className="text-sm font-medium text-space-black">
                ¥{minuteData[minuteData.length - 1]?.close.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-1">均价</div>
              <div className="text-sm font-medium text-space-black">
                ¥{minuteData[minuteData.length - 1]?.avg_price.toFixed(2)}
              </div>
            </div>
          </div>
        </GlassCard>
      ) : (
        <GlassCard className="p-4 rounded-[7px]">
          <div className="text-center text-gray-400 py-8">
            {selectedDate} 暂无分时数据
          </div>
        </GlassCard>
      )}
    </div>
  );
};

export default MinuteTab;
