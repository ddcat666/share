import React from 'react';
import type { PromptTemplate } from '../../types';

interface TemplateCardProps {
  template: PromptTemplate;
  isSelected?: boolean;
  onClick?: () => void;
}

// 占位符中文名称映射
const PLACEHOLDER_LABELS: Record<string, string> = {
  cash: '现金',
  market_value: '市值',
  total_assets: '总资产',
  return_rate: '收益率',
  positions: '持仓',
  portfolio_status: '持仓状态',
  market_data: '行情',
  current_market: '市场行情',
  stock_list: '股票列表',
  tech_indicators: '技术指标',
  fund_flow: '资金流向',
  financial_data: '财务数据',
  sentiment_score: '情绪分数',
  market_sentiment: '市场情绪',
  history_trades: '交易历史',
  hot_stocks: '热门股票',
};

/**
 * 模板卡片组件
 * 展示单个提示词模板的基本信息
 */
export const TemplateCard: React.FC<TemplateCardProps> = ({
  template,
  isSelected = false,
  onClick,
}) => {
  // Format date
  const formatDate = (dateStr: string) => {
    // 后端返回的是中国时间字符串（无时区信息），需要直接解析
    // 添加 'T' 和时区信息以确保正确解析
    const date = new Date(dateStr.replace(' ', 'T') + '+08:00');
    return date.toLocaleDateString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
    });
  };

  // Extract placeholders from content
  const extractPlaceholders = (content: string): string[] => {
    const regex = /\{\{(\w+)\}\}/g;
    const matches: string[] = [];
    let match;
    while ((match = regex.exec(content)) !== null) {
      if (!matches.includes(match[1])) {
        matches.push(match[1]);
      }
    }
    return matches;
  };

  const placeholders = extractPlaceholders(template.content);
  const contentLength = template.content.length;

  return (
    <div
      onClick={onClick}
      className={`
        group relative p-3 rounded-lg cursor-pointer
        transition-all duration-200 border
        ${isSelected 
          ? 'bg-space-black/5 border-space-black/20 shadow-sm' 
          : 'bg-white/60 border-gray-100 hover:bg-white hover:border-gray-200 hover:shadow-sm'
        }
      `}
    >
      {/* 选中指示器 */}
      {isSelected && (
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-space-black rounded-r-full" />
      )}

      {/* Header */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {/* 模板图标 */}
          <div className={`
            w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0
            ${isSelected ? 'bg-space-black text-white' : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200'}
          `}>
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          
          {/* 名称 */}
          <div className="min-w-0 flex-1">
            <h3 className={`font-semibol text-left truncate text-sm ${isSelected ? 'text-space-black' : 'text-gray-800'}`}>
              {template.name}
            </h3>
            <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
              <span>v{template.version}</span>
              <span>·</span>
              <span>{formatDate(template.updated_at)}</span>
              <span>·</span>
              <span>{contentLength > 1000 ? `${(contentLength / 1000).toFixed(1)}k` : contentLength} 字符</span>
            </div>
          </div>
        </div>

        {/* 箭头 */}
        <svg 
          className={`w-4 h-4 flex-shrink-0 transition-transform ${isSelected ? 'text-space-black' : 'text-gray-300 group-hover:text-gray-400'}`} 
          fill="none" 
          viewBox="0 0 24 24" 
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </div>

      {/* Placeholders */}
      {placeholders.length > 0 && (
        <div className="flex flex-wrap gap-1 pl-10">
          {placeholders.slice(0, 5).map((placeholder, index) => (
            <span
              key={index}
              className={`
                px-1.5 py-0.5 text-[10px] font-medium rounded
                ${isSelected 
                  ? 'bg-space-black/10 text-space-black' 
                  : 'bg-info-blue/10 text-info-blue'
                }
              `}
              title={`{{${placeholder}}}`}
            >
              {PLACEHOLDER_LABELS[placeholder] || placeholder}
            </span>
          ))}
          {placeholders.length > 5 && (
            <span className="text-[10px] text-gray-400 px-1">
              +{placeholders.length - 5}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export default TemplateCard;
