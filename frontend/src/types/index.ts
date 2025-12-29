// Enums as const objects (compatible with erasableSyntaxOnly)
export const OrderSide = {
  BUY: 'buy',
  SELL: 'sell',
  HOLD: 'hold',
} as const;
export type OrderSide = typeof OrderSide[keyof typeof OrderSide];

export const OrderStatus = {
  PENDING: 'pending',
  FILLED: 'filled',
  REJECTED: 'rejected',
  CANCELLED: 'cancelled',
} as const;
export type OrderStatus = typeof OrderStatus[keyof typeof OrderStatus];

export const DecisionType = {
  BUY: 'buy',
  SELL: 'sell',
  HOLD: 'hold',
  WAIT: 'wait',
} as const;
export type DecisionType = typeof DecisionType[keyof typeof DecisionType];

export const AgentStatus = {
  ACTIVE: 'active',
  PAUSED: 'paused',
  DELETED: 'deleted',
} as const;
export type AgentStatus = typeof AgentStatus[keyof typeof AgentStatus];

// Data Models
export interface StockQuote {
  stock_code: string;
  trade_date: string;
  open_price: number;
  high_price: number;
  low_price: number;
  close_price: number;
  prev_close: number;
  volume: number;
  amount: number;
}

export interface Position {
  stock_code: string;
  stock_name?: string;  // 股票名称
  shares: number;
  avg_cost: number;
  buy_date: string;
  sell_date?: string;  // 卖出日期（历史持仓）
  current_price?: number;
  market_value?: number;
  profit_loss?: number;
  profit_loss_rate?: number;
}

export interface Portfolio {
  agent_id: string;
  cash: number;
  positions: Position[];
  total_assets?: number;
  total_market_value?: number;
  return_rate?: number;
}

export interface TradingFees {
  commission: number;
  stamp_tax: number;
  transfer_fee: number;
  total: number;
}

export interface Order {
  order_id: string;
  agent_id: string;
  stock_code: string;
  side: OrderSide;
  quantity: number;
  price: number;
  created_at: string;
  status: OrderStatus;
  reject_reason?: string;
}

export interface Transaction {
  tx_id: string;
  order_id: string;
  agent_id: string;
  stock_code: string;
  stock_name?: string;  // 股票名称
  side: OrderSide;
  quantity: number;
  price: number;
  fees: TradingFees;
  executed_at: string;
  reason?: string;  // AI交易理由
}

export interface ModelAgent {
  agent_id: string;
  name: string;
  initial_cash: number;
  current_cash: number;
  template_id: string;
  provider_id: string;
  provider_name?: string;  // 模型渠道名称
  llm_model: string;
  status: AgentStatus;
  schedule_type: string;
  created_at: string;
  updated_at?: string;
  // 实时计算的字段
  total_assets?: number;
  total_market_value?: number;
  return_rate?: number;
  positions_count?: number;  // 持仓数量
  transactions_count?: number;  // 交易记录数量
  transactions?: Transaction[];  // 交易记录列表
}

export interface PromptTemplate {
  template_id: string;
  name: string;
  content: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface PortfolioMetrics {
  total_assets: number;
  total_market_value: number;
  cash: number;
  return_rate: number;
  annual_return_rate?: number;
  max_drawdown?: number;
  sharpe_ratio?: number;
}

// API Request/Response Types
export interface CreateAgentRequest {
  name: string;
  initial_cash?: number;
  template_id: string;
  provider_id: string;
  llm_model: string;
  schedule_type?: string;
}

export interface UpdateAgentRequest {
  name?: string;
  template_id?: string;
  provider_id?: string;
  llm_model?: string;
  schedule_type?: string;
  status?: AgentStatus;
}

export interface CreateTemplateRequest {
  name: string;
  content: string;
}

export interface UpdateTemplateRequest {
  name?: string;
  content?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ApiError {
  detail: string;
  code?: string;
  field?: string;
}

export interface LLMProvider {
  provider_id: string;
  name: string;
  protocol: string;
  api_url: string;
  api_key_masked: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMModel {
  id: string;
  name: string;
}

// ============== 系统任务相关类型 ==============

export const TaskStatus = {
  ACTIVE: 'active',
  PAUSED: 'paused',
} as const;
export type TaskStatus = typeof TaskStatus[keyof typeof TaskStatus];

export const TaskLogStatus = {
  RUNNING: 'running',
  SUCCESS: 'success',
  FAILED: 'failed',
  SKIPPED: 'skipped',
} as const;
export type TaskLogStatus = typeof TaskLogStatus[keyof typeof TaskLogStatus];

/**
 * 任务类型
 */
export const TaskType = {
  AGENT_DECISION: 'agent_decision',
  QUOTE_SYNC: 'quote_sync',
  MARKET_REFRESH: 'market_refresh',
} as const;
export type TaskType = typeof TaskType[keyof typeof TaskType];

export const AgentResultStatus = {
  SUCCESS: 'success',
  FAILED: 'failed',
  SKIPPED: 'skipped',
} as const;
export type AgentResultStatus = typeof AgentResultStatus[keyof typeof AgentResultStatus];

/**
 * 系统任务接口
 */
export interface SystemTask {
  task_id: string;
  name: string;
  task_type: TaskType;
  cron_expression: string;
  cron_description: string;
  agent_ids: string[];
  config: Record<string, unknown>;
  trading_day_only: boolean;
  status: TaskStatus;
  next_run_time: string | null;
  success_count: number;
  fail_count: number;
  created_at: string;
}

/**
 * 创建任务请求
 */
export interface TaskCreate {
  name: string;
  task_type: TaskType;
  cron_expression: string;
  agent_ids?: string[];
  config?: Record<string, unknown>;
  trading_day_only: boolean;
}

/**
 * 更新任务请求
 */
export interface TaskUpdate {
  name?: string;
  task_type?: TaskType;
  cron_expression?: string;
  agent_ids?: string[];
  config?: Record<string, unknown>;
  trading_day_only?: boolean;
}

/**
 * Agent执行结果
 */
export interface AgentResult {
  agent_id: string;
  agent_name: string;
  status: AgentResultStatus;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
}

/**
 * 任务日志摘要
 */
export interface TaskLog {
  log_id: number;
  started_at: string;
  completed_at: string | null;
  status: TaskLogStatus;
  duration_ms: number | null;
  agent_success_count: number;
  agent_fail_count: number;
}

/**
 * 任务日志详情
 */
export interface TaskLogDetail {
  log_id: number;
  task_id: string;
  started_at: string;
  completed_at: string | null;
  status: TaskLogStatus;
  duration_ms: number | null;
  skip_reason: string | null;
  error_message: string | null;
  agent_results: AgentResult[];
}

/**
 * 任务列表响应
 */
export interface TaskListResponse {
  tasks: SystemTask[];
  total: number;
}

/**
 * 任务日志列表响应
 */
export interface TaskLogListResponse {
  logs: TaskLog[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
