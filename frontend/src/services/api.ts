import axios, { type AxiosError, type AxiosInstance, type AxiosResponse } from 'axios';
import type {
  ModelAgent,
  CreateAgentRequest,
  UpdateAgentRequest,
  PromptTemplate,
  CreateTemplateRequest,
  UpdateTemplateRequest,
  StockQuote,
  Portfolio,
  Position,
  Transaction,
  PortfolioMetrics,
  PaginatedResponse,
  ApiError,
  SystemTask,
  TaskCreate,
  TaskUpdate,
  TaskLog,
  TaskLogDetail,
  TaskListResponse,
  TaskLogListResponse,
} from '../types';

// API Base URL - can be configured via environment variable
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// Token storage key
const TOKEN_KEY = 'admin_token';

// Create axios instance with default configuration
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Custom event for auth errors
export const AUTH_ERROR_EVENT = 'auth:token_expired';

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError<ApiError & { error_code?: string; message?: string }>) => {
    const responseData = error.response?.data;
    
    // Handle TOKEN_EXPIRED error
    if (responseData?.error_code === 'TOKEN_EXPIRED') {
      // Clear token
      localStorage.removeItem(TOKEN_KEY);
      // Dispatch custom event for UI to handle
      window.dispatchEvent(new CustomEvent(AUTH_ERROR_EVENT, {
        detail: { message: responseData.message || '登录已过期，请重新登录' }
      }));
    }
    
    const apiError: ApiError = {
      detail: responseData?.message || responseData?.detail || error.message || '请求失败',
      code: responseData?.error_code || error.code,
    };
    return Promise.reject(apiError);
  }
);

// Pagination parameters
interface PaginationParams {
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

// Backend response types (different from frontend PaginatedResponse)
interface AgentListResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  agents: ModelAgent[];
}

interface TransactionListResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  transactions: Transaction[];
}

interface TemplateListResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  templates: PromptTemplate[];
}

// ============ Agent API ============
export const agentApi = {
  // Create a new agent
  create: async (data: CreateAgentRequest): Promise<ModelAgent> => {
    const response = await apiClient.post<ModelAgent>('/agents', data);
    return response.data;
  },

  // List all agents with pagination
  list: async (params?: PaginationParams & { include_transactions?: boolean }): Promise<PaginatedResponse<ModelAgent>> => {
    const response = await apiClient.get<AgentListResponse>('/agents', { params });
    // Transform backend response to frontend format
    return {
      items: response.data.agents || [],
      total: response.data.total,
      page: response.data.page,
      page_size: response.data.page_size,
      total_pages: response.data.total_pages,
    };
  },

  // Get agent by ID
  getById: async (agentId: string): Promise<ModelAgent> => {
    const response = await apiClient.get<ModelAgent>(`/agents/${agentId}`);
    return response.data;
  },

  // Update agent
  update: async (agentId: string, data: UpdateAgentRequest): Promise<ModelAgent> => {
    const response = await apiClient.put<ModelAgent>(`/agents/${agentId}`, data);
    return response.data;
  },

  // Delete agent
  delete: async (agentId: string): Promise<void> => {
    await apiClient.delete(`/agents/${agentId}`);
  },

  // Trigger decision manually
  triggerDecision: async (agentId: string): Promise<{ success: boolean; message?: string; error_message?: string }> => {
    const response = await apiClient.post<{ success: boolean; message?: string; error_message?: string }>(`/agents/${agentId}/trigger`);
    return response.data;
  },

  // Trigger all active agents' decisions
  triggerAllDecisions: async (): Promise<{
    success: boolean;
    message: string;
    total: number;
    success_count: number;
    results: Array<{
      agent_id: string;
      agent_name: string;
      success: boolean;
      decision?: unknown;
      error?: string;
    }>;
  }> => {
    const response = await apiClient.post('/agents/trigger-all');
    return response.data;
  },

  // Get agent portfolio
  getPortfolio: async (agentId: string): Promise<Portfolio> => {
    const response = await apiClient.get<Portfolio>(`/agents/${agentId}/portfolio`);
    return response.data;
  },

  // Get agent transactions
  getTransactions: async (
    agentId: string,
    params?: PaginationParams & { start_date?: string; end_date?: string; side?: string }
  ): Promise<PaginatedResponse<Transaction>> => {
    const response = await apiClient.get<TransactionListResponse>(
      `/agents/${agentId}/transactions`,
      { params }
    );
    // Transform backend response to frontend format
    return {
      items: response.data.transactions || [],
      total: response.data.total,
      page: response.data.page,
      page_size: response.data.page_size,
      total_pages: response.data.total_pages,
    };
  },

  // Get agent metrics
  getMetrics: async (agentId: string): Promise<PortfolioMetrics> => {
    const response = await apiClient.get<{
      total_assets: number;
      total_market_value: number;
      cash_balance: number;
      return_rate: number;
      annualized_return?: number;
      max_drawdown?: number;
      sharpe_ratio?: number;
    }>(`/agents/${agentId}/metrics`);
    // Map backend field names to frontend field names
    // Backend returns return_rate as decimal (0.05 = 5%), frontend expects percentage (5)
    return {
      total_assets: response.data.total_assets,
      total_market_value: response.data.total_market_value,
      cash: response.data.cash_balance,
      return_rate: response.data.return_rate * 100,
      annual_return_rate: response.data.annualized_return,
      max_drawdown: response.data.max_drawdown ? response.data.max_drawdown * 100 : undefined,
      sharpe_ratio: response.data.sharpe_ratio,
    };
  },

  // Get agent asset history
  getAssetHistory: async (
    agentId: string,
    params?: { start_date?: string; end_date?: string }
  ): Promise<Array<{ date: string; value: number }>> => {
    const response = await apiClient.get<Array<{ date: string; value: number }>>(
      `/agents/${agentId}/asset-history`,
      { params }
    );
    return response.data;
  },

  // Get all agents asset histories (batch)
  getAllAssetHistories: async (): Promise<Record<string, {
    agent_id: string;
    name: string;
    history: Array<{ date: string; value: number }>;
  }>> => {
    const response = await apiClient.get('/agents/asset-histories');
    return response.data;
  },

  // Get agent history positions (已清仓的股票)
  getHistoryPositions: async (agentId: string): Promise<Position[]> => {
    const response = await apiClient.get<Position[]>(`/agents/${agentId}/history-positions`);
    return response.data;
  },

  // Get all agents positions summary (持仓汇总)
  getPositionsSummary: async (): Promise<{
    stocks: Array<{
      stock_code: string;
      stock_name: string;
      positions: Array<{
        agent_id: string;
        agent_name: string;
        shares: number;
        market_value: number;
      }>;
    }>;
    agents: Array<{
      agent_id: string;
      name: string;
      llm_model: string;
    }>;
  }> => {
    const response = await apiClient.get('/agents/positions/summary');
    return response.data;
  },
};

// ============ Template API ============
interface PlaceholderInfo {
  name: string;
  label: string;
  category: string;
  description: string;
}

interface PlaceholdersResponse {
  placeholders: PlaceholderInfo[];
  categories: Record<string, Array<{ name: string; label: string; description: string }>>;
}

export const templateApi = {
  // Create a new template
  create: async (data: CreateTemplateRequest): Promise<PromptTemplate> => {
    const response = await apiClient.post<PromptTemplate>('/templates', data);
    return response.data;
  },

  // List all templates with pagination
  list: async (params?: PaginationParams): Promise<PaginatedResponse<PromptTemplate>> => {
    const response = await apiClient.get<TemplateListResponse>('/templates', { params });
    // Transform backend response to frontend format
    return {
      items: response.data.templates || [],
      total: response.data.total,
      page: response.data.page,
      page_size: response.data.page_size,
      total_pages: response.data.total_pages,
    };
  },

  // Get template by ID
  getById: async (templateId: string): Promise<PromptTemplate> => {
    const response = await apiClient.get<PromptTemplate>(`/templates/${templateId}`);
    return response.data;
  },

  // Update template
  update: async (templateId: string, data: UpdateTemplateRequest): Promise<PromptTemplate> => {
    const response = await apiClient.put<PromptTemplate>(`/templates/${templateId}`, data);
    return response.data;
  },

  // Delete template
  delete: async (templateId: string): Promise<void> => {
    await apiClient.delete(`/templates/${templateId}`);
  },

  // Get available placeholders
  getPlaceholders: async (): Promise<PlaceholdersResponse> => {
    const response = await apiClient.get<PlaceholdersResponse>('/templates/placeholders');
    return response.data;
  },
};

// ============ Quotes API ============
export interface StockQuoteListItem {
  stock_code: string;
  stock_name: string | null;
  trade_date: string;
  open_price: number;
  high_price: number;
  low_price: number;
  close_price: number;
  prev_close: number;
  change_pct: number;
  volume: number;
  amount: number;
  created_at: string | null;
  record_count: number;
}

export interface StockQuoteListResponse {
  items: StockQuoteListItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface StockHistoryItem {
  stock_code: string;
  stock_name: string | null;
  trade_date: string;
  open_price: number;
  high_price: number;
  low_price: number;
  close_price: number;
  prev_close: number;
  change_pct: number;
  volume: number;
  amount: number;
  created_at: string | null;
}

export interface StockHistoryResponse {
  items: StockHistoryItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const quotesApi = {
  // Get stock list with latest quotes
  list: async (params?: { page?: number; page_size?: number; search?: string }): Promise<StockQuoteListResponse> => {
    const response = await apiClient.get<StockQuoteListResponse>('/quotes', { params });
    return response.data;
  },

  // Get current quote for a stock
  getCurrent: async (stockCode: string): Promise<StockQuote> => {
    const response = await apiClient.get<StockQuote>(`/quotes/${stockCode}`);
    return response.data;
  },

  // Get historical quotes
  getHistory: async (
    stockCode: string,
    params?: { start_date?: string; end_date?: string }
  ): Promise<StockQuote[]> => {
    const response = await apiClient.get<StockQuote[]>(`/quotes/${stockCode}/history`, { params });
    return response.data;
  },

  // Get all history for a stock (paginated)
  getAllHistory: async (
    stockCode: string,
    params?: { page?: number; page_size?: number }
  ): Promise<StockHistoryResponse> => {
    const response = await apiClient.get<StockHistoryResponse>(`/quotes/${stockCode}/all`, { params });
    return response.data;
  },

  // Refresh single stock quote
  refresh: async (stockCode: string): Promise<{ success: boolean; message: string; updated_count?: number }> => {
    const response = await apiClient.post<{ success: boolean; message: string; updated_count?: number }>(`/quotes/${stockCode}/refresh`);
    return response.data;
  },
};

// ============ Compare API ============
export const compareApi = {
  // Compare multiple agents
  compare: async (
    agentIds: string[],
    params?: { start_date?: string; end_date?: string }
  ): Promise<{
    agents: Array<{
      agent_id: string;
      name: string;
      metrics: PortfolioMetrics;
      asset_curve: Array<{ date: string; value: number }>;
    }>;
  }> => {
    const response = await apiClient.post('/compare', {
      agent_ids: agentIds,
      ...params,
    });
    return response.data;
  },
};

// ============ LLM Provider API ============
interface LLMProviderListResponse {
  providers: Array<{
    provider_id: string;
    name: string;
    protocol: string;
    api_url: string;
    api_key_masked: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
  }>;
}

interface LLMModel {
  id: string;
  name: string;
}

export const llmProviderApi = {
  // List all providers
  list: async (): Promise<LLMProviderListResponse['providers']> => {
    const response = await apiClient.get<LLMProviderListResponse>('/llm-providers');
    return response.data.providers || [];
  },

  // Get models for a provider
  getModels: async (providerId: string): Promise<LLMModel[]> => {
    const response = await apiClient.get<LLMModel[]>(`/llm-providers/${providerId}/models`);
    return response.data;
  },

  // Get API statistics overview
  getStatsOverview: async () => {
    const response = await apiClient.get('/llm-providers/stats/overview');
    return response.data;
  },
};

// ============ System Config API ============
interface SystemConfig {
  data_source: string;
  tushare_token: string;
  commission_rate: string;
  stamp_tax_rate: string;
  transfer_fee_rate: string;
}

export const systemApi = {
  // Get system config
  getConfig: async (): Promise<SystemConfig> => {
    const response = await apiClient.get<SystemConfig>('/system');
    return response.data;
  },

  // Update system config
  updateConfig: async (config: SystemConfig): Promise<SystemConfig> => {
    const response = await apiClient.put<SystemConfig>('/system', config);
    return response.data;
  },
};

// ============ Task API ============

/**
 * Cron表达式验证响应
 */
export interface CronValidateResponse {
  valid: boolean;
  description: string;
  error: string | null;
  next_run_time: string | null;
}

/**
 * 系统任务管理API
 */
export const taskApi = {
  /**
   * 验证Cron表达式
   */
  validateCron: async (cronExpression: string): Promise<CronValidateResponse> => {
    const response = await apiClient.post<CronValidateResponse>('/tasks/cron/validate', {
      cron_expression: cronExpression,
    });
    return response.data;
  },

  /**
   * 获取任务列表
   */
  list: async (): Promise<TaskListResponse> => {
    const response = await apiClient.get<TaskListResponse>('/tasks');
    return response.data;
  },

  /**
   * 创建任务
   */
  create: async (data: TaskCreate): Promise<SystemTask> => {
    const response = await apiClient.post<SystemTask>('/tasks', data);
    return response.data;
  },

  /**
   * 更新任务
   */
  update: async (taskId: string, data: TaskUpdate): Promise<SystemTask> => {
    const response = await apiClient.put<SystemTask>(`/tasks/${taskId}`, data);
    return response.data;
  },

  /**
   * 删除任务
   */
  delete: async (taskId: string): Promise<{ success: boolean; message: string }> => {
    const response = await apiClient.delete<{ success: boolean; message: string }>(`/tasks/${taskId}`);
    return response.data;
  },

  /**
   * 暂停任务
   */
  pause: async (taskId: string): Promise<SystemTask> => {
    const response = await apiClient.post<SystemTask>(`/tasks/${taskId}/pause`);
    return response.data;
  },

  /**
   * 恢复任务
   */
  resume: async (taskId: string): Promise<SystemTask> => {
    const response = await apiClient.post<SystemTask>(`/tasks/${taskId}/resume`);
    return response.data;
  },

  /**
   * 手动触发任务
   */
  trigger: async (taskId: string): Promise<{ success: boolean; message: string; log_id?: number; status?: string }> => {
    const response = await apiClient.post<{ success: boolean; message: string; log_id?: number; status?: string }>(`/tasks/${taskId}/trigger`);
    return response.data;
  },

  /**
   * 获取任务日志列表
   */
  getLogs: async (
    taskId: string,
    params?: { page?: number; page_size?: number }
  ): Promise<TaskLogListResponse> => {
    const response = await apiClient.get<TaskLogListResponse>(`/tasks/${taskId}/logs`, { params });
    return response.data;
  },

  /**
   * 获取任务日志详情
   */
  getLogDetail: async (taskId: string, logId: number): Promise<TaskLogDetail> => {
    const response = await apiClient.get<TaskLogDetail>(`/tasks/${taskId}/logs/${logId}`);
    return response.data;
  },
};

// ============ Auth API ============
interface AuthStatusResponse {
  auth_enabled: boolean;
  is_authenticated: boolean;
}

interface LoginResponse {
  success: boolean;
  token: string | null;
  message: string;
}

export const authApi = {
  // Get auth status
  getStatus: async (): Promise<AuthStatusResponse> => {
    const response = await apiClient.get<AuthStatusResponse>('/auth/status');
    return response.data;
  },

  // Login with secret key
  login: async (secretKey: string): Promise<LoginResponse> => {
    const response = await apiClient.post<LoginResponse>('/auth/login', {
      secret_key: secretKey,
    });
    return response.data;
  },

  // Logout
  logout: async (): Promise<void> => {
    await apiClient.post('/auth/logout');
  },
};

// ============ Market Data API ============
export interface MarketSentiment {
  fear_greed_index: number;
  market_mood: string;
  trading_activity: string;
  up_count?: number;
  down_count?: number;
  flat_count?: number;
  total_count?: number;
  limit_up_count?: number;
  limit_down_count?: number;
  updated_at?: string;
}

export interface IndexData {
  name: string;
  code: string;
  current: number;
  change: number;
  change_pct: number;
  volume: number;
  amount: number;
}

export interface HotStock {
  code: string;
  name: string;
  current_price: number;
  change_pct: number;
  volume: number;
  amount: number;
  turnover_rate: number;
}

export interface HotStocksResponse {
  data: { stocks: HotStock[]; updated_at: string } | null;
  date: string;
  updated_at: string;
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}

export interface MarketDataResponse {
  market_sentiment: {
    data: MarketSentiment;
    date: string;
    updated_at: string;
  } | null;
  index_overview: {
    data: { indices: IndexData[]; updated_at: string };
    date: string;
    updated_at: string;
  } | null;
  hot_stocks: {
    data: { stocks: HotStock[]; updated_at: string };
    date: string;
    updated_at: string;
  } | null;
}

export const marketApi = {
  // Get all market data
  getAll: async (): Promise<MarketDataResponse> => {
    const response = await apiClient.get<MarketDataResponse>('/market');
    return response.data;
  },

  // Get market overview (for dashboard)
  getOverview: async () => {
    const response = await apiClient.get('/market/overview');
    return response.data;
  },

  // Get market sentiment
  getSentiment: async () => {
    const response = await apiClient.get('/market/sentiment');
    return response.data;
  },

  // Get index overview
  getIndices: async () => {
    const response = await apiClient.get('/market/indices');
    return response.data;
  },

  // Get hot stocks
  getHotStocks: async (page: number = 1, pageSize: number = 20): Promise<HotStocksResponse> => {
    const response = await apiClient.get<HotStocksResponse>('/market/hot-stocks', {
      params: { page, page_size: pageSize }
    });
    return response.data;
  },

  // Refresh all market data
  refreshAll: async (): Promise<{ success: boolean; results: Record<string, boolean>; message: string }> => {
    const response = await apiClient.post('/market/refresh');
    return response.data;
  },

  // Refresh market sentiment
  refreshSentiment: async () => {
    const response = await apiClient.post('/market/refresh/sentiment');
    return response.data;
  },

  // Refresh indices
  refreshIndices: async () => {
    const response = await apiClient.post('/market/refresh/indices');
    return response.data;
  },

  // Refresh hot stocks
  refreshHotStocks: async () => {
    const response = await apiClient.post('/market/refresh/hot-stocks');
    return response.data;
  },
};

// ============ Stock Detail API Types ============

// 股票基本信息
export interface StockBasicInfo {
  code: string;           // 股票代码
  name: string;           // 股票名称
  market: 'SH' | 'SZ';    // 市场（上海/深圳）
  industry: string;       // 所属行业
  list_date: string;      // 上市日期
}

// 股票实时行情
export interface StockRealtimeQuote {
  price: number;          // 当前价格
  change: number;         // 涨跌额
  change_pct: number;     // 涨跌幅
  open: number;           // 今开
  high: number;           // 最高
  low: number;            // 最低
  prev_close: number;     // 昨收
  volume: number;         // 成交量
  amount: number;         // 成交额
  turnover_rate: number;  // 换手率
  pe: number;             // 市盈率
  pb: number;             // 市净率
  market_cap: number;     // 总市值
  updated_at: string;     // 更新时间
}

// K线数据
export interface KLineData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

export interface KLineListResponse {
  stock_code: string;
  period: string;
  data: KLineData[];
}

// 分时数据
export interface MinuteData {
  time: string;           // 时间 (YYYY-MM-DD HH:MM:SS)
  open: number;           // 开盘价
  high: number;           // 最高价
  low: number;            // 最低价
  close: number;          // 收盘价
  volume: number;         // 成交量
  amount: number;         // 成交额
  avg_price: number;      // 均价
}

export interface MinuteDataListResponse {
  stock_code: string;
  period: string;
  data: MinuteData[];
}

// 资金流向数据
export interface CapitalFlowData {
  date: string;
  main_inflow: number;     // 主力流入
  main_outflow: number;    // 主力流出
  main_net: number;        // 主力净流入
  retail_inflow: number;   // 散户流入
  retail_outflow: number;  // 散户流出
  retail_net: number;      // 散户净流入
  total_inflow: number;    // 总流入
  total_outflow: number;   // 总流出
  total_net: number;       // 净流入
}

export interface CapitalFlowListResponse {
  stock_code: string;
  data: CapitalFlowData[];
}

// 资金分布
export interface CapitalDistributionItem {
  inflow: number;
  outflow: number;
  net: number;
}

export interface CapitalDistribution {
  stock_code: string;
  super_large: CapitalDistributionItem;  // 超大单
  large: CapitalDistributionItem;        // 大单
  medium: CapitalDistributionItem;       // 中单
  small: CapitalDistributionItem;        // 小单
}

// 公司简介
export interface CompanyProfile {
  name: string;              // 公司名称
  english_name: string;      // 英文名称
  industry: string;          // 所属行业
  list_date: string;         // 上市日期
  total_shares: number;      // 总股本
  circulating_shares: number; // 流通股本
  description: string;       // 公司简介
  main_business: string;     // 主营业务
  registered_capital: number; // 注册资本
  employees: number;         // 员工人数
  province: string;          // 所在省份
  city: string;              // 所在城市
  website: string;           // 公司网站
}

// 股东信息
export interface Shareholder {
  name: string;              // 股东名称
  shares: number;            // 持股数量
  percentage: number;        // 持股比例
  nature: string;            // 股东性质
}

export interface ShareholderListResponse {
  stock_code: string;
  shareholders: Shareholder[];
}

// 股票新闻
export interface StockNews {
  id: string;
  title: string;             // 新闻标题
  source: string;            // 来源
  publish_time: string;      // 发布时间
  url: string;               // 链接
  sentiment: 'positive' | 'negative' | 'neutral';  // 情感
  summary: string;           // 摘要
}

export interface StockNewsListResponse {
  stock_code: string;
  page: number;
  page_size: number;
  data: StockNews[];
}

// 机构评级
export interface AnalystRating {
  institution: string;       // 机构名称
  analyst: string;           // 分析师
  rating: string;            // 评级（买入/增持/中性/减持/卖出）
  target_price: number;      // 目标价
  date: string;              // 日期
}

export interface AnalystRatingListResponse {
  stock_code: string;
  ratings: AnalystRating[];
}

// 财务指标
export interface FinancialMetrics {
  report_date: string;        // 报告期
  revenue: number;           // 营业收入
  revenue_yoy: number;       // 营收同比
  net_profit: number;        // 净利润
  net_profit_yoy: number;    // 净利润同比
  gross_margin: number;      // 毛利率
  net_margin: number;        // 净利率
  roe: number;               // 净资产收益率
  eps: number;               // 每股收益
  bps: number;               // 每股净资产
}

export interface FinancialMetricsListResponse {
  stock_code: string;
  report_type: string;
  data: FinancialMetrics[];
}

// 资产负债表
export interface BalanceSheet {
  report_date: string;        // 报告期
  total_assets: number;       // 总资产
  total_liabilities: number;  // 总负债
  total_equity: number;       // 股东权益
  current_assets: number;     // 流动资产
  current_liabilities: number;// 流动负债
  cash_and_equivalents: number;// 货币资金
}

export interface BalanceSheetListResponse {
  stock_code: string;
  data: BalanceSheet[];
}

// 现金流量表
export interface CashFlow {
  report_date: string;        // 报告期
  operating_cash_flow: number; // 经营活动现金流
  investing_cash_flow: number; // 投资活动现金流
  financing_cash_flow: number; // 筹资活动现金流
  net_cash_flow: number;       // 现金净流量
}

export interface CashFlowListResponse {
  stock_code: string;
  data: CashFlow[];
}

// AI分析相关类型
export interface TechnicalIndicator {
  name: string;
  value: string;
  signal: 'positive' | 'negative' | 'neutral';
}

export interface TechnicalAnalysis {
  summary: string;         // 技术面总结
  trend: 'bullish' | 'bearish' | 'neutral';
  indicators: TechnicalIndicator[];
}

export interface FundamentalAnalysis {
  summary: string;         // 基本面总结
  valuation: 'undervalued' | 'fair' | 'overvalued';
  highlights: string[];    // 亮点
  concerns: string[];      // 风险点
}

export interface SentimentAnalysis {
  summary: string;         // 舆情总结
  sentiment: 'positive' | 'negative' | 'neutral';
  news_highlights: string[];
}

export interface AIAnalysisResult {
  stock_code: string;
  stock_name: string;
  analysis_time: string;
  overall_rating: 'strong_buy' | 'buy' | 'neutral' | 'cautious' | 'avoid';
  rating_score: number;       // 1-5分
  technical_analysis: TechnicalAnalysis;
  fundamental_analysis: FundamentalAnalysis;
  sentiment_analysis: SentimentAnalysis;
  investment_points: string[];  // 投资要点
  risk_warnings: string[];      // 风险提示
  conclusion: string;          // 总结
}

// ============ Stock Detail API ============
export const stockApi = {
  // 获取股票基本信息
  getInfo: async (stockCode: string): Promise<StockBasicInfo> => {
    const response = await apiClient.get<StockBasicInfo>(`/stock/${stockCode}/info`);
    return response.data;
  },

  // 获取实时行情
  getQuote: async (stockCode: string): Promise<StockRealtimeQuote> => {
    const response = await apiClient.get<StockRealtimeQuote>(`/stock/${stockCode}/quote`);
    return response.data;
  },

  // 获取K线数据
  getKLine: async (
    stockCode: string,
    params?: {
      period?: 'daily' | 'weekly' | 'monthly';
      start_date?: string;
      end_date?: string;
      limit?: number;
    }
  ): Promise<KLineListResponse> => {
    const response = await apiClient.get<KLineListResponse>(`/stock/${stockCode}/kline`, { params });
    return response.data;
  },

  // 获取资金流向
  getCapitalFlow: async (
    stockCode: string,
    days: number = 5
  ): Promise<CapitalFlowListResponse> => {
    const response = await apiClient.get<CapitalFlowListResponse>(`/stock/${stockCode}/capital-flow`, {
      params: { days },
    });
    return response.data;
  },

  // 获取资金分布
  getCapitalDistribution: async (stockCode: string): Promise<CapitalDistribution> => {
    const response = await apiClient.get<CapitalDistribution>(`/stock/${stockCode}/capital-distribution`);
    return response.data;
  },

  // 获取公司简介
  getProfile: async (stockCode: string): Promise<CompanyProfile> => {
    const response = await apiClient.get<CompanyProfile>(`/stock/${stockCode}/profile`);
    return response.data;
  },

  // 获取股东信息
  getShareholders: async (stockCode: string): Promise<ShareholderListResponse> => {
    const response = await apiClient.get<ShareholderListResponse>(`/stock/${stockCode}/shareholders`);
    return response.data;
  },

  // 获取股票新闻
  getNews: async (
    stockCode: string,
    params?: { page?: number; page_size?: number }
  ): Promise<StockNewsListResponse> => {
    const response = await apiClient.get<StockNewsListResponse>(`/stock/${stockCode}/news`, { params });
    return response.data;
  },

  // 获取机构评级
  getAnalystRatings: async (stockCode: string): Promise<AnalystRatingListResponse> => {
    const response = await apiClient.get<AnalystRatingListResponse>(`/stock/${stockCode}/analyst-ratings`);
    return response.data;
  },

  // 获取财务指标
  getFinancials: async (
    stockCode: string,
    params?: { report_type?: 'quarterly' | 'annual'; periods?: number }
  ): Promise<FinancialMetricsListResponse> => {
    const response = await apiClient.get<FinancialMetricsListResponse>(`/stock/${stockCode}/financials`, { params });
    return response.data;
  },

  // 获取资产负债表
  getBalanceSheet: async (
    stockCode: string,
    periods: number = 4
  ): Promise<BalanceSheetListResponse> => {
    const response = await apiClient.get<BalanceSheetListResponse>(`/stock/${stockCode}/balance-sheet`, {
      params: { periods },
    });
    return response.data;
  },

  // 获取现金流量表
  getCashFlow: async (
    stockCode: string,
    periods: number = 4
  ): Promise<CashFlowListResponse> => {
    const response = await apiClient.get<CashFlowListResponse>(`/stock/${stockCode}/cash-flow`, {
      params: { periods },
    });
    return response.data;
  },

  // 生成AI分析报告
  generateAIAnalysis: async (
    stockCode: string,
    forceRefresh: boolean = false
  ): Promise<AIAnalysisResult> => {
    const response = await apiClient.post<AIAnalysisResult>(`/stock/${stockCode}/ai-analysis`, {
      force_refresh: forceRefresh,
    });
    return response.data;
  },

  // 获取缓存的AI分析报告
  getAIAnalysis: async (stockCode: string): Promise<AIAnalysisResult | null> => {
    const response = await apiClient.get<AIAnalysisResult | null>(`/stock/${stockCode}/ai-analysis`);
    return response.data;
  },

  // 获取分时数据
  getMinuteData: async (
    stockCode: string,
    params?: {
      period?: '1' | '5' | '15' | '30' | '60';
      start_date?: string;
      end_date?: string;
    }
  ): Promise<MinuteDataListResponse> => {
    const response = await apiClient.get<MinuteDataListResponse>(`/stock/${stockCode}/minute`, { params });
    return response.data;
  },
};

// Export the axios instance for custom requests
export { apiClient };

// Export all APIs as a single object
export const api = {
  agents: agentApi,
  templates: templateApi,
  quotes: quotesApi,
  compare: compareApi,
  llmProviders: llmProviderApi,
  system: systemApi,
  tasks: taskApi,
  auth: authApi,
  market: marketApi,
  stock: stockApi,
};

export default api;
