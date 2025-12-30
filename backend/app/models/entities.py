"""核心实体数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from app.models.enums import OrderSide, OrderStatus, DecisionType, AgentStatus, LLMProtocol


@dataclass
class StockQuote:
    """股票行情"""

    stock_code: str
    trade_date: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    prev_close: Decimal
    volume: int
    amount: Decimal
    stock_name: Optional[str] = None  # 股票名称


@dataclass
class Position:
    """持仓"""

    stock_code: str
    shares: int
    avg_cost: Decimal
    buy_date: str  # 用于T+1判断


@dataclass
class Portfolio:
    """投资组合"""

    agent_id: str
    cash: Decimal
    positions: List[Position] = field(default_factory=list)


@dataclass
class TradingFees:
    """交易费用"""

    commission: Decimal  # 佣金
    stamp_tax: Decimal  # 印花税
    transfer_fee: Decimal  # 过户费

    @property
    def total(self) -> Decimal:
        """总费用"""
        return self.commission + self.stamp_tax + self.transfer_fee


@dataclass
class Order:
    """订单"""

    order_id: str
    agent_id: str
    stock_code: str
    side: OrderSide
    quantity: int
    price: Decimal
    created_at: datetime
    status: OrderStatus = OrderStatus.PENDING
    reject_reason: Optional[str] = None
    reason: Optional[str] = None  # AI交易理由
    llm_request_log_id: Optional[int] = None  # 关联的LLM请求日志ID


@dataclass
class Transaction:
    """成交记录"""

    tx_id: str
    order_id: str
    agent_id: str
    stock_code: str
    side: OrderSide
    quantity: int
    price: Decimal
    fees: TradingFees
    executed_at: datetime


@dataclass
class TradingDecision:
    """AI交易决策"""

    decision: DecisionType
    reason: str
    stock_code: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[Decimal] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "decision": self.decision.value,
            "stock_code": self.stock_code,
            "quantity": self.quantity,
            "price": str(self.price) if self.price else None,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingDecision":
        """从字典创建"""
        return cls(
            decision=DecisionType(data["decision"]),
            stock_code=data.get("stock_code"),
            quantity=data.get("quantity"),
            price=Decimal(data["price"]) if data.get("price") else None,
            reason=data.get("reason", ""),
        )


@dataclass
class ModelAgent:
    """模型代理"""

    agent_id: str
    name: str
    initial_cash: Decimal
    template_id: str
    provider_id: str  # LLM渠道ID
    llm_model: str
    created_at: datetime
    status: AgentStatus = AgentStatus.ACTIVE
    current_cash: Optional[Decimal] = None
    schedule_type: str = "daily"
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.current_cash is None:
            self.current_cash = self.initial_cash


@dataclass
class PromptTemplate:
    """提示词模板"""

    template_id: str
    name: str
    content: str
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass
class PromptContext:
    """提示词上下文数据"""

    current_market: Dict[str, Any]  # 当前市场数据
    history_trades: List[Dict[str, Any]]  # 历史交易
    financial_data: Dict[str, Any]  # 财务数据
    portfolio_status: Dict[str, Any]  # 持仓状态
    sentiment_score: float  # 情绪分数
    
    # 账户资产类
    cash: Optional[Decimal] = None  # 可用现金
    market_value: Optional[Decimal] = None  # 持仓市值
    total_assets: Optional[Decimal] = None  # 总资产
    return_rate: Optional[Decimal] = None  # 收益率
    positions: Optional[List[Dict[str, Any]]] = None  # 持仓列表
    positions_quotes: Optional[str] = None  # 持仓股票历史行情（markdown表格）
    market_data: Optional[Dict[str, Any]] = None  # 市场数据（同 current_market）
    
    # 技术指标类
    tech_indicators: Optional[Dict[str, Any]] = None  # 技术分析指标
    ma_data: Optional[Dict[str, Any]] = None  # 均线数据
    macd_data: Optional[Dict[str, Any]] = None  # MACD指标
    kdj_data: Optional[Dict[str, Any]] = None  # KDJ指标
    rsi_data: Optional[Dict[str, Any]] = None  # RSI指标
    boll_data: Optional[Dict[str, Any]] = None  # 布林带
    
    # 资金流向类
    fund_flow: Optional[Dict[str, Any]] = None  # 个股资金流向
    fund_flow_rank: Optional[List[Dict[str, Any]]] = None  # 资金流向排行
    north_fund: Optional[Dict[str, Any]] = None  # 北向资金
    
    # 财务指标类
    financial_indicator: Optional[Dict[str, Any]] = None  # 财务分析指标
    profit_data: Optional[Dict[str, Any]] = None  # 利润数据
    balance_data: Optional[Dict[str, Any]] = None  # 资产负债
    cashflow_data: Optional[Dict[str, Any]] = None  # 现金流
    
    # 市场情绪类
    news_sentiment: Optional[Dict[str, Any]] = None  # 新闻情绪
    market_sentiment: Optional[Dict[str, Any]] = None  # 市场情绪
    
    # 历史数据类
    history_quotes: Optional[List[Dict[str, Any]]] = None  # 历史行情
    history_decisions: Optional[List[Dict[str, Any]]] = None  # 决策历史
    
    # 市场概况类
    stock_list: Optional[List[str]] = None  # 股票列表
    market_overview: Optional[Dict[str, Any]] = None  # 大盘概况
    sector_flow: Optional[Dict[str, Any]] = None  # 板块资金
    hot_stocks: Optional[List[Dict[str, Any]]] = None  # 热门股票
    hot_stocks_quotes: Optional[str] = None  # 热门股票近3日行情（markdown表格）
    limit_up_down: Optional[Dict[str, Any]] = None  # 涨跌停统计
    
    # 系统时间类
    current_time: Optional[str] = None  # 当前时间 HH:MM:SS
    current_date: Optional[str] = None  # 当前日期 YYYY-MM-DD
    current_weekday: Optional[str] = None  # 星期几
    is_trading_day: Optional[bool] = None  # 是否交易日
    
    # 涨停板数据类
    limit_up_order_amount: Optional[str] = None  # 封单金额（亿元）
    queue_amount: Optional[str] = None  # 当前排队金额
    queue_position: Optional[str] = None  # 预估排队位置


@dataclass
class ValidationResult:
    """验证结果"""

    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class PortfolioMetrics:
    """投资组合指标"""

    total_assets: Decimal  # 总资产
    total_market_value: Decimal  # 持仓市值
    cash_balance: Decimal  # 现金余额
    total_return: Decimal  # 累计收益
    return_rate: Decimal  # 收益率
    annualized_return: Optional[Decimal] = None  # 年化收益率
    max_drawdown: Optional[Decimal] = None  # 最大回撤
    sharpe_ratio: Optional[Decimal] = None  # 夏普比率


@dataclass
class LLMProvider:
    """LLM渠道配置"""

    provider_id: str
    name: str
    protocol: LLMProtocol
    api_url: str
    api_key: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class LLMModel:
    """LLM模型信息"""

    id: str
    name: str
    provider_id: str
