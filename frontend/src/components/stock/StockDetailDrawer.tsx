import React, { useEffect, useState, useCallback } from 'react';
import { stockApi, type StockBasicInfo, type StockRealtimeQuote } from '../../services/api';
import { StockHeader } from './StockHeader';
import { OverviewTab } from './tabs/OverviewTab';
import { MinuteTab } from './tabs/MinuteTab';
import { CapitalTab } from './tabs/CapitalTab';
import { ProfileTab } from './tabs/ProfileTab';
import { NewsTab } from './tabs/NewsTab';
import { FinanceTab } from './tabs/FinanceTab';
import { AIAnalysisTab } from './tabs/AIAnalysisTab';

export interface StockDetailDrawerProps {
  stockCode: string | null;
  onClose: () => void;
}

// 标签类型
type TabType = 'overview' | 'minute' | 'capital' | 'profile' | 'news' | 'finance' | 'ai-analysis';

// 标签配置
const TAB_CONFIG: { key: TabType; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'minute', label: '分时' },
  { key: 'capital', label: '资金' },
  { key: 'profile', label: '简况' },
  { key: 'news', label: '资讯' },
  { key: 'finance', label: '财务' },
  { key: 'ai-analysis', label: 'AI分析' },
];

/**
 * 股票详情抽屉组件
 * 右侧滑出，占页面80%宽度
 * 需求: 2.1, 2.2, 2.3, 2.4, 11.1, 11.3, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4, 12.5
 */
export const StockDetailDrawer: React.FC<StockDetailDrawerProps> = ({ stockCode, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [stockInfo, setStockInfo] = useState<StockBasicInfo | null>(null);
  const [quote, setQuote] = useState<StockRealtimeQuote | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true); // 自动刷新开关

  // 加载股票基本信息和实时行情
  const loadStockData = useCallback(async (code: string) => {
    setLoading(true);
    setError(null);
    try {
      const [infoResponse, quoteResponse] = await Promise.all([
        stockApi.getInfo(code),
        stockApi.getQuote(code),
      ]);

      setStockInfo(infoResponse);
      setQuote(quoteResponse);
    } catch (err) {
      console.error('加载股票数据失败:', err);
      setError('加载股票数据失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, []);

  // 刷新实时行情（不显示loading）
  const refreshQuote = useCallback(async (code: string) => {
    try {
      const quoteResponse = await stockApi.getQuote(code);
      setQuote(quoteResponse);
    } catch (err) {
      console.error('刷新行情失败:', err);
    }
  }, []);

  // 刷新数据
  const handleRefresh = useCallback(() => {
    if (stockCode) {
      loadStockData(stockCode);
    }
  }, [stockCode, loadStockData]);

  useEffect(() => {
    if (stockCode) {
      loadStockData(stockCode);
      // 重置为默认标签页
      setActiveTab('overview');
    }
  }, [stockCode, loadStockData]);

  // 自动刷新实时行情（每5秒）
  useEffect(() => {
    if (!stockCode || !autoRefresh) return;

    const interval = setInterval(() => {
      refreshQuote(stockCode);
    }, 5000); // 5秒刷新一次

    return () => clearInterval(interval);
  }, [stockCode, autoRefresh, refreshQuote]);

  // 点击遮罩关闭
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  // ESC键关闭 & 阻止页面滚动
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    if (stockCode) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [stockCode, onClose]);

  // 处理标签切换
  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
  };

  // 渲染当前标签页内容
  const renderTabContent = () => {
    if (!stockCode) return null;

    switch (activeTab) {
      case 'overview':
        return <OverviewTab stockCode={stockCode} />;
      case 'minute':
        return <MinuteTab stockCode={stockCode} />;
      case 'capital':
        return <CapitalTab stockCode={stockCode} />;
      case 'profile':
        return <ProfileTab stockCode={stockCode} />;
      case 'news':
        return <NewsTab stockCode={stockCode} />;
      case 'finance':
        return <FinanceTab stockCode={stockCode} />;
      case 'ai-analysis':
        return <AIAnalysisTab stockCode={stockCode} />;
      default:
        return <OverviewTab stockCode={stockCode} />;
    }
  };

  if (!stockCode) return null;

  return (
    <div 
      className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm"
      onClick={handleBackdropClick}
      data-testid="stock-detail-drawer-backdrop"
    >
      {/* 抽屉内容 */}
      <div 
        className="absolute right-0 top-0 h-full w-[80%] bg-ios-gray shadow-2xl overflow-hidden animate-slide-in-right"
        data-testid="stock-detail-drawer"
      >
        {/* 头部区域 - 固定 */}
        <div className="sticky top-0 z-10 bg-white/80 backdrop-blur-md border-b border-gray-200/50">
          {/* 关闭按钮 + 股票头部信息 */}
          <div className="flex items-start">
            {/* 关闭按钮和自动刷新开关 */}
            <div className="flex-shrink-0 p-3 flex items-center gap-2">
              <button
                onClick={onClose}
                className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
                data-testid="close-button"
                title="关闭"
              >
                <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>

              {/* 自动刷新开关 */}
              <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`p-2 rounded-lg transition-colors ${autoRefresh ? 'bg-info-blue/10 text-info-blue' : 'hover:bg-gray-100 text-gray-500'}`}
                title={autoRefresh ? '关闭自动刷新' : '开启自动刷新（每5秒）'}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>

            {/* 股票头部信息 */}
            <div className="flex-1 min-w-0">
              <StockHeader
                stockInfo={stockInfo}
                quote={quote}
                onRefresh={handleRefresh}
                loading={loading}
              />
            </div>
          </div>

          {/* Tab菜单 */}
          <div className="px-6 pb-0">
            <div className="flex gap-1 border-b border-gray-200" data-testid="tab-menu">
              {TAB_CONFIG.map(tab => (
                <button
                  key={tab.key}
                  onClick={() => handleTabChange(tab.key)}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === tab.key
                      ? 'border-space-black text-space-black'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                  data-testid={`tab-${tab.key}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 内容区域 - 可滚动 */}
        <div className="h-[calc(100%-10px)] overflow-y-auto p-6" data-testid="drawer-content">
          {error ? (
            <div className="flex flex-col items-center justify-center h-64">
              <svg className="w-12 h-12 text-red-400 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <p className="text-gray-600 mb-4">{error}</p>
              <button
                onClick={handleRefresh}
                className="px-4 py-2 bg-space-black text-white rounded-lg text-sm hover:bg-gray-800 transition-colors"
                data-testid="retry-button"
              >
                重试
              </button>
            </div>
          ) : (
            renderTabContent()
          )}
        </div>
      </div>
    </div>
  );
};

export default StockDetailDrawer;
