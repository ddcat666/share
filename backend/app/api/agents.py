"""Model Agent API路由"""

import uuid
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.repositories import ModelAgentRepository, PortfolioRepository, PositionRepository
from app.ai.agent_manager import ModelAgentManager
from app.models.entities import ModelAgent
from app.models.enums import AgentStatus
from app.api.schemas import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentListResponse,
    TriggerDecisionRequest,
    TriggerDecisionResponse,
    ErrorResponse,
    PaginationParams,
)
from app.data.repositories import StockQuoteRepository
from app.core.timezone import now as tz_now
from app.core.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局Agent管理器实例（用于内存操作和决策执行）
_agent_manager = ModelAgentManager()


def get_agent_manager() -> ModelAgentManager:
    """获取Agent管理器实例"""
    return _agent_manager


def _calculate_agent_assets(agent: ModelAgent, db: Session) -> tuple[Decimal, Decimal, Decimal, int, int]:
    """计算Agent的实时资产（优化版本，避免N+1查询）
    
    Returns:
        tuple: (总资产, 持仓市值, 收益率, 持仓数量, 交易记录数量)
    """
    from app.db.models import TransactionModel, PositionModel, StockQuoteModel
    from sqlalchemy import func
    
    # 批量获取持仓
    positions = (
        db.query(PositionModel)
        .filter(PositionModel.agent_id == agent.agent_id)
        .all()
    )
    
    if not positions:
        # 无持仓时直接返回
        current_cash = agent.current_cash or agent.initial_cash
        return_rate = Decimal("0")
        if agent.initial_cash > 0:
            return_rate = ((current_cash - agent.initial_cash) / agent.initial_cash) * 100
        
        transactions_count = db.query(func.count(TransactionModel.tx_id)).filter(
            TransactionModel.agent_id == agent.agent_id
        ).scalar() or 0
        
        return current_cash, Decimal("0"), return_rate, 0, transactions_count
    
    # 批量获取所有持仓股票的最新行情
    stock_codes = [p.stock_code for p in positions]
    
    # 使用子查询获取每只股票的最新行情日期
    latest_dates_subquery = (
        db.query(
            StockQuoteModel.stock_code,
            func.max(StockQuoteModel.trade_date).label("max_date")
        )
        .filter(StockQuoteModel.stock_code.in_(stock_codes))
        .group_by(StockQuoteModel.stock_code)
        .subquery()
    )
    
    # 获取最新行情
    latest_quotes = (
        db.query(StockQuoteModel)
        .join(
            latest_dates_subquery,
            (StockQuoteModel.stock_code == latest_dates_subquery.c.stock_code) &
            (StockQuoteModel.trade_date == latest_dates_subquery.c.max_date)
        )
        .all()
    )
    
    # 构建价格字典
    price_map = {q.stock_code: Decimal(str(q.close_price)) for q in latest_quotes}
    
    # 计算持仓市值
    total_market_value = Decimal("0")
    for pos in positions:
        current_price = price_map.get(pos.stock_code, Decimal(str(pos.avg_cost)))
        total_market_value += current_price * pos.shares
    
    # 计算总资产 = 当前现金 + 持仓市值
    current_cash = agent.current_cash or agent.initial_cash
    total_assets = current_cash + total_market_value
    
    # 计算收益率
    if agent.initial_cash > 0:
        return_rate = ((total_assets - agent.initial_cash) / agent.initial_cash) * 100
    else:
        return_rate = Decimal("0")
    
    # 获取交易记录数量
    transactions_count = db.query(func.count(TransactionModel.tx_id)).filter(
        TransactionModel.agent_id == agent.agent_id
    ).scalar() or 0
    
    return total_assets, total_market_value, return_rate, len(positions), transactions_count


def _get_market_data_for_prompt(db: Session) -> str:
    """获取股票最近15条行情数据，用于提示词
    
    返回简洁的字符串格式，便于 LLM 理解
    格式: 股票代码|日期|开|高|低|收|涨跌%|量(万手)
    
    注意：为避免超出模型上下文限制，最多返回50只股票的数据
    """
    from app.db.models import StockQuoteModel
    from sqlalchemy import func
    
    # 获取有行情数据的股票代码（按最新交易日期排序，取前50只）
    subquery = (
        db.query(
            StockQuoteModel.stock_code,
            func.max(StockQuoteModel.trade_date).label("latest_date")
        )
        .group_by(StockQuoteModel.stock_code)
        .order_by(func.max(StockQuoteModel.trade_date).desc())
        .limit(50)
        .subquery()
    )
    
    stock_codes = [row[0] for row in db.query(subquery.c.stock_code).all()]
    
    if not stock_codes:
        return "暂无行情数据"
    
    # 获取每只股票最近15条数据
    lines = []
    lines.append("股票|日期|开|高|低|收|涨跌%|量(万手)")
    lines.append("-" * 50)
    
    for code in stock_codes:
        quotes = (
            db.query(StockQuoteModel)
            .filter(StockQuoteModel.stock_code == code)
            .order_by(StockQuoteModel.trade_date.desc())
            .limit(15)
            .all()
        )
        
        # 按日期正序排列
        quotes = list(reversed(quotes))
        
        for q in quotes:
            change_pct = 0
            if q.prev_close and float(q.prev_close) > 0:
                change_pct = round((float(q.close_price) - float(q.prev_close)) / float(q.prev_close) * 100, 2)
            
            vol_wan = round(q.volume / 10000, 1) if q.volume else 0
            
            line = f"{q.stock_code}|{q.trade_date.strftime('%m-%d')}|{float(q.open_price):.2f}|{float(q.high_price):.2f}|{float(q.low_price):.2f}|{float(q.close_price):.2f}|{change_pct:+.2f}%|{vol_wan}"
            lines.append(line)
    
    return "\n".join(lines)


def _get_hot_stocks_quotes(db: Session) -> str:
    """获取热门股票最近3天行情数据
    
    1. 从 market_data 表获取 data_type='hot_stocks' 的热门股票
    2. 根据股票代码从 stock_quotes 获取最近3天数据
    3. 返回 markdown 表格格式
    """
    from app.db.models import MarketDataModel, StockQuoteModel
    
    # 1. 获取热门股票数据
    hot_stocks_record = (
        db.query(MarketDataModel)
        .filter(MarketDataModel.data_type == "hot_stocks")
        .order_by(MarketDataModel.data_date.desc())
        .first()
    )
    
    if not hot_stocks_record or not hot_stocks_record.data_content:
        return "暂无热门股票数据"
    
    # 2. 解析热门股票代码
    data_content = hot_stocks_record.data_content
    stocks = data_content.get("stocks", []) if isinstance(data_content, dict) else []
    
    if not stocks:
        return "暂无热门股票数据"
    
    # 提取股票代码
    stock_codes = [s.get("code") for s in stocks if s.get("code")]
    
    if not stock_codes:
        return "暂无热门股票数据"
    
    # 3. 获取每只股票最近3天行情
    lines = []
    lines.append("## 热门股票近3日行情")
    lines.append("")
    lines.append("| 股票代码 | 股票名称 | 日期 | 开盘 | 最高 | 最低 | 收盘 | 涨跌幅 | 成交量(万手) |")
    lines.append("|----------|----------|------|------|------|------|------|--------|--------------|")
    
    for code in stock_codes[:20]:  # 最多20只热门股票
        quotes = (
            db.query(StockQuoteModel)
            .filter(StockQuoteModel.stock_code == code)
            .order_by(StockQuoteModel.trade_date.desc())
            .limit(3)
            .all()
        )
        
        # 按日期正序排列
        quotes = list(reversed(quotes))
        
        for q in quotes:
            change_pct = 0
            if q.prev_close and float(q.prev_close) > 0:
                change_pct = round((float(q.close_price) - float(q.prev_close)) / float(q.prev_close) * 100, 2)
            
            vol_wan = round(q.volume / 10000, 1) if q.volume else 0
            stock_name = q.stock_name or "-"
            
            line = f"| {q.stock_code} | {stock_name} | {q.trade_date.strftime('%m-%d')} | {float(q.open_price):.2f} | {float(q.high_price):.2f} | {float(q.low_price):.2f} | {float(q.close_price):.2f} | {change_pct:+.2f}% | {vol_wan} |"
            lines.append(line)
    
    return "\n".join(lines)


def _get_positions_quotes(db: Session, agent_id: str) -> str:
    """获取当前持仓股票的全部行情数据
    
    1. 获取 agent 当前持仓的股票代码
    2. 从 stock_quotes 获取这些股票的全部历史数据
    3. 返回 markdown 表格格式
    """
    from app.db.models import PositionModel, StockQuoteModel
    
    # 1. 获取当前持仓股票代码
    positions = (
        db.query(PositionModel)
        .filter(PositionModel.agent_id == agent_id)
        .filter(PositionModel.shares > 0)
        .all()
    )
    
    if not positions:
        return "当前无持仓"
    
    stock_codes = [p.stock_code for p in positions]
    
    # 构建持仓信息映射
    position_map = {p.stock_code: {"shares": p.shares, "avg_cost": float(p.avg_cost)} for p in positions}
    
    # 2. 获取每只股票的全部行情数据
    lines = []
    lines.append("## 持仓股票历史行情")
    lines.append("")
    
    for code in stock_codes:
        pos_info = position_map[code]
        
        quotes = (
            db.query(StockQuoteModel)
            .filter(StockQuoteModel.stock_code == code)
            .order_by(StockQuoteModel.trade_date.desc())
            .limit(30)  # 最多30条历史数据
            .all()
        )
        
        if not quotes:
            continue
        
        # 按日期正序排列
        quotes = list(reversed(quotes))
        stock_name = quotes[0].stock_name or code
        
        lines.append(f"### {code} {stock_name}")
        lines.append(f"持仓: {pos_info['shares']}股, 成本价: {pos_info['avg_cost']:.2f}")
        lines.append("")
        lines.append("| 日期 | 开盘 | 最高 | 最低 | 收盘 | 涨跌幅 | 成交量(万手) |")
        lines.append("|------|------|------|------|------|--------|--------------|")
        
        for q in quotes:
            change_pct = 0
            if q.prev_close and float(q.prev_close) > 0:
                change_pct = round((float(q.close_price) - float(q.prev_close)) / float(q.prev_close) * 100, 2)
            
            vol_wan = round(q.volume / 10000, 1) if q.volume else 0
            
            line = f"| {q.trade_date.strftime('%m-%d')} | {float(q.open_price):.2f} | {float(q.high_price):.2f} | {float(q.low_price):.2f} | {float(q.close_price):.2f} | {change_pct:+.2f}% | {vol_wan} |"
            lines.append(line)
        
        lines.append("")
    
    return "\n".join(lines)


def _model_to_response(agent: ModelAgent, db: Session = None, include_transactions: bool = False) -> AgentResponse:
    """将ModelAgent转换为响应模型"""
    from app.db.repositories import TransactionRepository, OrderRepository
    from app.api.schemas import TransactionResponse
    from decimal import Decimal
    
    # 如果提供了db，计算实时资产
    total_assets = None
    total_market_value = None
    return_rate = None
    positions_count = None
    transactions_count = None
    provider_name = None
    transactions_list = None
    
    if db:
        total_assets, total_market_value, return_rate, positions_count, transactions_count = _calculate_agent_assets(agent, db)
        
        # 查询 provider_name
        if agent.provider_id:
            from app.db.models import LLMProviderModel
            provider = db.query(LLMProviderModel).filter(
                LLMProviderModel.provider_id == agent.provider_id
            ).first()
            if provider:
                provider_name = provider.name
        
        # 如果需要包含交易记录
        if include_transactions:
            from app.db.models import StockQuoteModel
            from sqlalchemy import func
            
            tx_repo = TransactionRepository(db)
            order_repo = OrderRepository(db)
            transactions = tx_repo.get_by_agent(agent.agent_id, limit=100, offset=0)
            
            # 批量查询股票名称
            stock_codes = [tx.stock_code for tx in transactions if tx.stock_code]
            stock_names = {}
            if stock_codes:
                # 获取每只股票的最新记录的名称
                latest_quotes = (
                    db.query(StockQuoteModel.stock_code, StockQuoteModel.stock_name)
                    .filter(StockQuoteModel.stock_code.in_(stock_codes))
                    .filter(StockQuoteModel.stock_name.isnot(None))
                    .distinct(StockQuoteModel.stock_code)
                    .all()
                )
                stock_names = {q.stock_code: q.stock_name for q in latest_quotes}
            
            tx_responses = []
            for tx in transactions:
                order = order_repo.get_by_id(tx.order_id)
                reason = order.reason if order else None
                
                total_fees = None
                if tx.fees.commission is not None or tx.fees.stamp_tax is not None or tx.fees.transfer_fee is not None:
                    total_fees = tx.fees.total
                
                tx_responses.append(TransactionResponse(
                    tx_id=tx.tx_id,
                    order_id=tx.order_id,
                    agent_id=tx.agent_id,
                    stock_code=tx.stock_code,
                    stock_name=stock_names.get(tx.stock_code) if tx.stock_code else None,
                    side=tx.side.value,
                    quantity=tx.quantity,
                    price=tx.price if tx.price and tx.price > 0 else None,
                    commission=tx.fees.commission if tx.fees.commission and tx.fees.commission > 0 else None,
                    stamp_tax=tx.fees.stamp_tax if tx.fees.stamp_tax and tx.fees.stamp_tax > 0 else None,
                    transfer_fee=tx.fees.transfer_fee if tx.fees.transfer_fee and tx.fees.transfer_fee > 0 else None,
                    total_fees=total_fees if total_fees and total_fees > 0 else None,
                    executed_at=tx.executed_at,
                    reason=reason,
                ))
            transactions_list = tx_responses
    
    return AgentResponse(
        agent_id=agent.agent_id,
        name=agent.name,
        initial_cash=agent.initial_cash,
        current_cash=agent.current_cash or agent.initial_cash,
        template_id=agent.template_id,
        provider_id=agent.provider_id,
        provider_name=provider_name,
        llm_model=agent.llm_model,
        status=agent.status.value if isinstance(agent.status, AgentStatus) else str(agent.status),
        schedule_type=agent.schedule_type,
        created_at=agent.created_at,
        total_assets=float(total_assets) if total_assets else None,
        total_market_value=float(total_market_value) if total_market_value else None,
        return_rate=float(return_rate) if return_rate else None,
        positions_count=positions_count,
        transactions_count=transactions_count,
        transactions=transactions_list,
    )


async def trigger_agent_decision(agent_id: str, db: Session) -> dict:
    """触发单个Agent的决策（供任务调度器调用）
    
    这是 trigger_decision API 端点的核心逻辑，提取出来供 task_executor 调用。
    使用分布式锁防止同一 Agent 并发执行决策。
    
    Args:
        agent_id: Agent ID
        db: 数据库会话
        
    Returns:
        dict: 包含 success 和 error_message 的结果字典
    """
    from app.db.models import LLMProviderModel, PromptTemplateModel, StockQuoteModel
    from app.ai.llm_client import MultiProtocolLLMClient
    from app.models.enums import LLMProtocol
    from app.models.entities import PromptTemplate, Portfolio
    from app.data.repositories import SentimentScoreRepository
    from app.core.locks import agent_decision_lock, LockAcquisitionError
    
    # 获取决策锁，防止同一 Agent 并发执行
    lock = agent_decision_lock(agent_id)
    if not await lock.acquire_async(blocking=False):
        logger.warning(f"Agent {agent_id} 正在执行决策，跳过本次触发")
        return {"success": False, "error_message": "Agent正在执行决策，请稍后重试"}
    
    try:
        repo = ModelAgentRepository(db)
        portfolio_repo = PortfolioRepository(db)
        agent = repo.get_by_id(agent_id)
        
        if agent is None or agent.status == AgentStatus.DELETED:
            return {"success": False, "error_message": f"Agent不存在: {agent_id}"}
        
        if agent.status == AgentStatus.PAUSED:
            return {"success": False, "error_message": "Agent已暂停，无法触发决策"}
        
        # 获取LLM Provider配置
        if not agent.provider_id:
            return {"success": False, "error_message": "Agent未配置LLM渠道"}
        
        provider = db.query(LLMProviderModel).filter(
            LLMProviderModel.provider_id == agent.provider_id
        ).first()
        
        if provider is None:
            return {"success": False, "error_message": f"LLM渠道不存在: {agent.provider_id}"}
        
        if not provider.is_active:
            return {"success": False, "error_message": f"LLM渠道已禁用: {provider.name}"}
        
        # 使用Agent管理器执行决策
        manager = get_agent_manager()
        
        # 初始化LLM客户端
        try:
            llm_client = MultiProtocolLLMClient(
                protocol=LLMProtocol(provider.protocol),
                api_base=provider.api_url,
                api_key=provider.api_key,
                default_model=agent.llm_model,
                provider_id=provider.provider_id,
            )
            llm_client.set_agent_id(agent_id)
            
            # 设置日志记录回调
            from app.db.models import LLMRequestLogModel
            latest_llm_log_id = [None]
            
            def log_llm_request(
                provider_id: str,
                model_name: str,
                agent_id: str,
                request_content: str,
                response_content: str,
            duration_ms: int,
            status: str,
            error_message: str,
            tokens_input: int,
            tokens_output: int,
        ):
            try:
                log_entry = LLMRequestLogModel(
                    provider_id=provider_id or "",
                    model_name=model_name or "",
                    agent_id=agent_id,
                    request_content=request_content[:10000] if request_content else "",
                    response_content=response_content[:10000] if response_content else None,
                    duration_ms=duration_ms,
                    status=status,
                    error_message=error_message,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                )
                db.add(log_entry)
                db.flush()
                latest_llm_log_id[0] = log_entry.id
                db.commit()
            except Exception as e:
                logger.error(f"记录LLM请求日志失败: {e}")
                db.rollback()
        
        llm_client.set_log_callback(log_llm_request)
        manager.llm_client = llm_client
    except Exception as e:
        return {"success": False, "error_message": f"初始化LLM客户端失败: {str(e)}"}
    
    # 加载模板
    if agent.template_id:
        template_model = db.query(PromptTemplateModel).filter(
            PromptTemplateModel.template_id == agent.template_id
        ).first()
        if template_model:
            template = PromptTemplate(
                template_id=template_model.template_id,
                name=template_model.name,
                content=template_model.content,
                version=template_model.version,
                created_at=template_model.created_at,
                updated_at=template_model.updated_at,
            )
            manager.prompt_manager._templates[agent.template_id] = template
    
    # 加载portfolio
    portfolio = portfolio_repo.get_by_agent_id(agent_id)
    if not portfolio:
        portfolio = Portfolio(
            agent_id=agent_id,
            cash=agent.current_cash or agent.initial_cash,
            positions=[],
        )
    
    # 准备市场数据
    market_data = _get_market_data_for_prompt(db)
    
    from app.data.market_service import MarketDataService
    market_service = MarketDataService(db)
    prompt_market_data = market_service.get_market_data_for_prompt()
    
    # 获取情绪分数
    sentiment_score = 0.0
    sentiment_repo = SentimentScoreRepository(db)
    latest_sentiment = sentiment_repo.get_latest()
    if latest_sentiment is not None:
        sentiment_score = latest_sentiment
    elif prompt_market_data.get("market_sentiment"):
        fear_greed = prompt_market_data["market_sentiment"].get("fear_greed_index", 50)
        sentiment_score = (fear_greed - 50) / 50
    
    hot_stocks_quotes = _get_hot_stocks_quotes(db)
    positions_quotes = _get_positions_quotes(db, agent_id)
    
    try:
        result = await manager.execute_decision_cycle(
            agent=agent,
            portfolio=portfolio,
            market_data=market_data,
            financial_data={},
            sentiment_score=sentiment_score,
            market_sentiment=prompt_market_data.get("market_sentiment"),
            index_overview=prompt_market_data.get("index_overview"),
            hot_stocks=prompt_market_data.get("hot_stocks"),
            hot_stocks_quotes=hot_stocks_quotes,
            positions_quotes=positions_quotes,
        )
        
        llm_log_id = latest_llm_log_id[0]
        
        # 如果决策成功，执行订单
        executed_orders = []
        if result.success and result.decisions:
            from app.core.order_processor import OrderProcessor
            from app.models.entities import Order
            from app.models.enums import OrderSide, OrderStatus
            from app.db.repositories import OrderRepository, TransactionRepository, PositionRepository
            from app.db.models import OrderModel, TransactionModel
            import uuid as uuid_module
            
            processor = OrderProcessor(check_trading_time=False)
            order_repo = OrderRepository(db)
            tx_repo = TransactionRepository(db)
            position_repo = PositionRepository(db)
            
            for decision in result.decisions:
                if decision.decision.value in ("hold", "wait"):
                    order_id = str(uuid_module.uuid4())
                    hold_order = OrderModel(
                        order_id=order_id,
                        agent_id=agent_id,
                        llm_request_log_id=llm_log_id,
                        stock_code=None,
                        side="hold",
                        quantity=None,
                        price=None,
                        status="filled",
                        reason=decision.reason,
                    )
                    db.add(hold_order)
                    
                    hold_tx = TransactionModel(
                        tx_id=str(uuid_module.uuid4()),
                        order_id=order_id,
                        agent_id=agent_id,
                        stock_code=None,
                        side="hold",
                        quantity=None,
                        price=None,
                        commission=None,
                        stamp_tax=None,
                        transfer_fee=None,
                    )
                    db.add(hold_tx)
                    db.commit()
                    continue
                
                if decision.decision.value not in ("buy", "sell"):
                    continue
                
                raw_stock_code = decision.stock_code or ""
                stock_code = raw_stock_code.split(".")[0] if "." in raw_stock_code else raw_stock_code
                quantity = decision.quantity
                
                stock_data = {}
                quote_model = (
                    db.query(StockQuoteModel)
                    .filter(StockQuoteModel.stock_code == stock_code)
                    .order_by(StockQuoteModel.trade_date.desc())
                    .first()
                )
                if quote_model:
                    stock_data = {
                        "close": float(quote_model.close_price),
                        "prev_close": float(quote_model.prev_close) if quote_model.prev_close else float(quote_model.close_price),
                    }
                
                price = Decimal(str(decision.price or stock_data.get("close", 0)))
                prev_close = Decimal(str(stock_data.get("prev_close", price)))
                
                if not stock_code or not quantity or quantity <= 0 or price <= 0:
                    continue
                
                order = Order(
                    order_id=str(uuid_module.uuid4()),
                    agent_id=agent_id,
                    stock_code=stock_code,
                    side=OrderSide.BUY if decision.decision.value == "buy" else OrderSide.SELL,
                    quantity=quantity,
                    price=price,
                    created_at=tz_now(),
                    status=OrderStatus.PENDING,
                    reason=decision.reason,
                    llm_request_log_id=llm_log_id,
                )
                
                order_result = processor.process_order(
                    order=order,
                    portfolio=portfolio,
                    prev_close=prev_close,
                )
                
                if order_result.success:
                    order_repo.save(order_result.order)
                    if order_result.transaction:
                        tx_repo.save(order_result.transaction)
                    position_repo.delete(agent_id, stock_code)
                    for pos in portfolio.positions:
                        if pos.stock_code == stock_code and pos.shares > 0:
                            position_repo.save(agent_id, pos)
                    executed_orders.append({
                        "stock_code": stock_code,
                        "side": decision.decision.value,
                        "quantity": quantity,
                        "price": float(price),
                    })
            
            if executed_orders:
                portfolio_repo.update_cash(agent_id, portfolio.cash)
                agent.current_cash = portfolio.cash
                repo.save(agent)
        
        return {
            "success": result.success,
            "executed_count": len(executed_orders),
            "error_message": result.error_message,
        }
        
    except Exception as e:
        logger.exception(f"Agent {agent_id} 决策执行失败: {e}")
        return {"success": False, "error_message": str(e)}
    finally:
        # 释放决策锁
        lock.release()


@router.get(
    "",
    response_model=AgentListResponse,
    summary="列出所有Agent",
    description="获取所有Model Agent的列表，支持分页和排序",
)
async def list_agents(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    sort_by: Optional[str] = Query(default=None, description="排序字段 (name, created_at)"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$", description="排序方向"),
    include_transactions: bool = Query(default=False, description="是否包含交易记录"),
    db: Session = Depends(get_db),
):
    """列出所有Agent"""
    repo = ModelAgentRepository(db)
    
    # 获取所有Agent
    all_agents = repo.get_all()
    
    # 按状态筛选
    if status:
        all_agents = [a for a in all_agents if a.status.value == status]
    
    # 排除已删除的Agent
    all_agents = [a for a in all_agents if a.status != AgentStatus.DELETED]
    
    # 排序
    if sort_by:
        reverse = sort_order == "desc"
        if sort_by == "name":
            all_agents.sort(key=lambda a: a.name, reverse=reverse)
        elif sort_by == "created_at":
            all_agents.sort(key=lambda a: a.created_at, reverse=reverse)
    else:
        # 默认按创建时间降序
        all_agents.sort(key=lambda a: a.created_at, reverse=True)
    
    # 计算分页
    total = len(all_agents)
    total_pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size
    
    # 分页
    paginated_agents = all_agents[offset:offset + page_size]
    
    return AgentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        agents=[_model_to_response(a, db, include_transactions=include_transactions) for a in paginated_agents],
    )


@router.post(
    "",
    response_model=AgentResponse,
    status_code=201,
    summary="创建Agent",
    description="创建一个新的Model Agent",
    responses={
        400: {"model": ErrorResponse, "description": "请求参数错误"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def create_agent(
    request: AgentCreate,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """创建Agent"""
    repo = ModelAgentRepository(db)
    
    # 生成Agent ID
    agent_id = str(uuid.uuid4())
    current_time = tz_now()
    
    # 创建Agent实体
    agent = ModelAgent(
        agent_id=agent_id,
        name=request.name,
        initial_cash=request.initial_cash,
        current_cash=request.initial_cash,
        template_id=request.template_id or "",
        provider_id=request.provider_id or "",
        llm_model=request.llm_model,
        status=AgentStatus.ACTIVE,
        schedule_type=request.schedule_type,
        created_at=current_time,
    )
    
    # 保存到数据库
    repo.save(agent)
    
    return _model_to_response(agent)


@router.get(
    "/asset-histories",
    summary="批量获取所有Agent资产历史",
    description="一次性获取所有活跃Agent的资产历史数据",
)
async def get_all_asset_histories(
    db: Session = Depends(get_db),
):
    """批量获取所有Agent资产历史
    
    返回所有活跃Agent的资产历史数据，避免前端多次调用
    """
    from datetime import date
    from app.core.portfolio_manager import calculate_total_assets
    
    agent_repo = ModelAgentRepository(db)
    portfolio_repo = PortfolioRepository(db)
    
    # 获取所有活跃的Agent
    agents = agent_repo.get_active()
    
    result = {}
    
    for agent in agents:
        portfolio = portfolio_repo.get_by_agent_id(agent.agent_id)
        if portfolio is None:
            continue
        
        # 获取市场价格计算当前资产
        stock_codes = [p.stock_code for p in portfolio.positions]
        market_prices = _get_market_prices_batch(db, stock_codes)
        current_assets = calculate_total_assets(portfolio, market_prices)
        
        # 构建资产历史
        history = [
            {"date": agent.created_at.strftime("%Y-%m-%d"), "value": float(agent.initial_cash)},
            {"date": date.today().strftime("%Y-%m-%d"), "value": float(current_assets)},
        ]
        
        result[agent.agent_id] = {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "history": history,
        }
    
    return result


def _get_market_prices_batch(db: Session, stock_codes: list) -> dict:
    """批量获取股票当前市场价格"""
    if not stock_codes:
        return {}
    
    from app.db.models import StockQuoteModel
    from sqlalchemy import func
    
    latest_dates_subquery = (
        db.query(
            StockQuoteModel.stock_code,
            func.max(StockQuoteModel.trade_date).label("max_date")
        )
        .filter(StockQuoteModel.stock_code.in_(stock_codes))
        .group_by(StockQuoteModel.stock_code)
        .subquery()
    )
    
    latest_quotes = (
        db.query(StockQuoteModel)
        .join(
            latest_dates_subquery,
            (StockQuoteModel.stock_code == latest_dates_subquery.c.stock_code) &
            (StockQuoteModel.trade_date == latest_dates_subquery.c.max_date)
        )
        .all()
    )
    
    return {q.stock_code: q.close_price for q in latest_quotes}


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="获取Agent详情",
    description="根据ID获取Agent的详细信息",
    responses={
        404: {"model": ErrorResponse, "description": "Agent不存在"},
    },
)
async def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
):
    """获取Agent详情"""
    repo = ModelAgentRepository(db)
    agent = repo.get_by_id(agent_id)
    
    if agent is None or agent.status == AgentStatus.DELETED:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_NOT_FOUND", "message": f"Agent不存在: {agent_id}"}
        )
    
    return _model_to_response(agent)


@router.put(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="更新Agent",
    description="更新Agent的配置信息",
    responses={
        404: {"model": ErrorResponse, "description": "Agent不存在"},
        400: {"model": ErrorResponse, "description": "请求参数错误"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def update_agent(
    agent_id: str,
    request: AgentUpdate,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """更新Agent"""
    repo = ModelAgentRepository(db)
    agent = repo.get_by_id(agent_id)
    
    if agent is None or agent.status == AgentStatus.DELETED:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_NOT_FOUND", "message": f"Agent不存在: {agent_id}"}
        )
    
    # 更新字段
    updated_agent = ModelAgent(
        agent_id=agent.agent_id,
        name=request.name if request.name is not None else agent.name,
        initial_cash=agent.initial_cash,
        current_cash=agent.current_cash,
        template_id=request.template_id if request.template_id is not None else agent.template_id,
        provider_id=request.provider_id if request.provider_id is not None else agent.provider_id,
        llm_model=request.llm_model if request.llm_model is not None else agent.llm_model,
        status=AgentStatus(request.status) if request.status is not None else agent.status,
        schedule_type=request.schedule_type if request.schedule_type is not None else agent.schedule_type,
        created_at=agent.created_at,
    )
    
    repo.save(updated_agent)
    
    return _model_to_response(updated_agent)


@router.delete(
    "/{agent_id}",
    status_code=204,
    summary="删除Agent",
    description="删除Agent（软删除）",
    responses={
        404: {"model": ErrorResponse, "description": "Agent不存在"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def delete_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """删除Agent"""
    repo = ModelAgentRepository(db)
    agent = repo.get_by_id(agent_id)
    
    if agent is None or agent.status == AgentStatus.DELETED:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_NOT_FOUND", "message": f"Agent不存在: {agent_id}"}
        )
    
    # 软删除
    repo.delete(agent_id)
    
    return None


@router.post(
    "/{agent_id}/trigger",
    response_model=TriggerDecisionResponse,
    summary="手动触发决策",
    description="手动触发Agent执行一次决策周期",
    responses={
        401: {"model": ErrorResponse, "description": "未授权"},
        404: {"model": ErrorResponse, "description": "Agent不存在"},
        400: {"model": ErrorResponse, "description": "Agent状态不允许触发决策"},
    },
)
async def trigger_decision(
    agent_id: str,
    request: TriggerDecisionRequest = None,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """手动触发决策"""
    from app.db.models import LLMProviderModel, PromptTemplateModel, StockQuoteModel
    from app.ai.llm_client import MultiProtocolLLMClient
    from app.models.enums import LLMProtocol
    from app.models.entities import PromptTemplate
    from app.data.repositories import StockQuoteRepository, SentimentScoreRepository
    from sqlalchemy import func
    from app.core.locks import agent_decision_lock
    
    # 获取决策锁，防止同一 Agent 并发执行
    lock = agent_decision_lock(agent_id)
    if not await lock.acquire_async(blocking=False):
        logger.warning(f"Agent {agent_id} 正在执行决策，跳过本次触发")
        return TriggerDecisionResponse(
            success=False,
            error_message="Agent正在执行决策，请稍后重试"
        )
    
    try:
        repo = ModelAgentRepository(db)
        portfolio_repo = PortfolioRepository(db)
        agent = repo.get_by_id(agent_id)
        
        if agent is None or agent.status == AgentStatus.DELETED:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "AGENT_NOT_FOUND", "message": f"Agent不存在: {agent_id}"}
            )
        
        if agent.status == AgentStatus.PAUSED:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "AGENT_PAUSED", "message": "Agent已暂停，无法触发决策"}
            )
        
        # 获取LLM Provider配置
        if not agent.provider_id:
            return TriggerDecisionResponse(
                success=False,
                error_message="Agent未配置LLM渠道，请先在Agent设置中选择渠道"
            )
        
        provider = db.query(LLMProviderModel).filter(
            LLMProviderModel.provider_id == agent.provider_id
        ).first()
        
        if provider is None:
            return TriggerDecisionResponse(
                success=False,
                error_message=f"LLM渠道不存在: {agent.provider_id}"
            )
        
        if not provider.is_active:
            return TriggerDecisionResponse(
                success=False,
                error_message=f"LLM渠道已禁用: {provider.name}"
            )
        
        # 使用Agent管理器执行决策
        manager = get_agent_manager()
        
        # 初始化LLM客户端
        llm_client = MultiProtocolLLMClient(
            protocol=LLMProtocol(provider.protocol),
            api_base=provider.api_url,
            api_key=provider.api_key,
            default_model=agent.llm_model,
            provider_id=provider.provider_id,
        )
        
        # 设置Agent ID用于日志记录
        llm_client.set_agent_id(agent_id)
        
        # 设置日志记录回调，保存最新的日志ID
        from app.db.models import LLMRequestLogModel
        latest_llm_log_id = [None]  # 用列表包装以便在闭包中修改
        
        def log_llm_request(
            provider_id: str,
            model_name: str,
            agent_id: str,
            request_content: str,
            response_content: str,
            duration_ms: int,
            status: str,
            error_message: str,
            tokens_input: int,
            tokens_output: int,
        ):
            try:
                log_entry = LLMRequestLogModel(
                    provider_id=provider_id or "",
                    model_name=model_name or "",
                    agent_id=agent_id,
                    request_content=request_content[:10000] if request_content else "",  # 限制长度
                    response_content=response_content[:10000] if response_content else None,
                    duration_ms=duration_ms,
                    status=status,
                    error_message=error_message,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                )
                db.add(log_entry)
                db.flush()  # 获取自增ID
                latest_llm_log_id[0] = log_entry.id
                db.commit()
                logger.info(f"LLM请求日志已记录: id={log_entry.id}")
            except Exception as e:
                logger.error(f"记录LLM请求日志失败: {e}")
                db.rollback()
        
        llm_client.set_log_callback(log_llm_request)
        manager.llm_client = llm_client
        
        # 如果agent配置了模板，从数据库加载到PromptManager
        if agent.template_id:
            template_model = db.query(PromptTemplateModel).filter(
                PromptTemplateModel.template_id == agent.template_id
            ).first()
            
            if template_model:
                template = PromptTemplate(
                    template_id=template_model.template_id,
                    name=template_model.name,
                    content=template_model.content,
                    version=template_model.version,
                    created_at=template_model.created_at,
                    updated_at=template_model.updated_at,
                )
                manager.prompt_manager._templates[agent.template_id] = template
        
        # 从数据库加载最新的portfolio
        portfolio = portfolio_repo.get_by_agent_id(agent_id)
        if not portfolio:
            # 创建空的portfolio
            from app.models.entities import Portfolio
            portfolio = Portfolio(
                agent_id=agent_id,
                cash=agent.current_cash or agent.initial_cash,
                positions=[],
            )
        
        # 准备请求数据
        if request is None:
            request = TriggerDecisionRequest()
        
        # 自动获取市场数据（如果请求中没有提供）
        market_data = request.market_data or {}
        if not market_data:
            market_data = _get_market_data_for_prompt(db)
        
        # 从数据库获取市场情绪和大盘数据
        from app.data.market_service import MarketDataService
        market_service = MarketDataService(db)
        prompt_market_data = market_service.get_market_data_for_prompt()
        
        # 自动获取情绪分数（如果请求中没有提供）
        sentiment_score = request.sentiment_score
        if sentiment_score == 0.0:
            sentiment_repo = SentimentScoreRepository(db)
            latest_sentiment = sentiment_repo.get_latest()
            if latest_sentiment is not None:
                sentiment_score = latest_sentiment
            # 如果数据库中有市场情绪数据，使用fear_greed_index作为情绪分数
            elif prompt_market_data.get("market_sentiment"):
                fear_greed = prompt_market_data["market_sentiment"].get("fear_greed_index", 50)
                # 将0-100的指数转换为-1到1的分数
                sentiment_score = (fear_greed - 50) / 50
        
        financial_data = request.financial_data or {}
        
        # 获取热门股票近3日行情
        hot_stocks_quotes = _get_hot_stocks_quotes(db)
        
        # 获取持仓股票历史行情
        positions_quotes = _get_positions_quotes(db, agent_id)
        
        result = await manager.execute_decision_cycle(
            agent=agent,
            portfolio=portfolio,
            market_data=market_data,
            financial_data=financial_data,
            sentiment_score=sentiment_score,
            market_sentiment=prompt_market_data.get("market_sentiment"),
            index_overview=prompt_market_data.get("index_overview"),
            hot_stocks=prompt_market_data.get("hot_stocks"),
            hot_stocks_quotes=hot_stocks_quotes,
            positions_quotes=positions_quotes,
        )
        
        # 获取本次LLM调用的日志ID
        llm_log_id = latest_llm_log_id[0]
        logger.info(f"Agent {agent_id} 决策完成，LLM日志ID: {llm_log_id}")
        
        # 如果决策成功，执行所有买入或卖出订单
        executed_orders = []
        if result.success and result.decisions:
            from app.core.order_processor import OrderProcessor
            from app.models.entities import Order
            from app.models.enums import OrderSide, OrderStatus
            from app.db.repositories import OrderRepository, TransactionRepository, PositionRepository
            from decimal import Decimal
            import uuid
            
            processor = OrderProcessor(check_trading_time=False)
            order_repo = OrderRepository(db)
            tx_repo = TransactionRepository(db)
            position_repo = PositionRepository(db)
                
            # 处理每个决策
            for decision in result.decisions:
                # hold/wait 决策：创建记录但不执行交易
                if decision.decision.value in ("hold", "wait"):
                    order_id = str(uuid.uuid4())
                    # 创建 hold 订单（无股票代码、数量、价格），关联LLM日志
                    from app.db.models import OrderModel, TransactionModel
                    hold_order = OrderModel(
                        order_id=order_id,
                        agent_id=agent_id,
                        llm_request_log_id=llm_log_id,  # 关联LLM请求日志
                        stock_code=None,
                        side="hold",
                        quantity=None,
                        price=None,
                        status="filled",  # hold 决策直接标记为已完成
                        reason=decision.reason,
                    )
                    db.add(hold_order)
                    
                    # 创建 hold 交易记录（无费用）
                    hold_tx = TransactionModel(
                        tx_id=str(uuid.uuid4()),
                        order_id=order_id,
                        agent_id=agent_id,
                        stock_code=None,
                        side="hold",
                        quantity=None,
                        price=None,
                        commission=None,
                        stamp_tax=None,
                        transfer_fee=None,
                    )
                    db.add(hold_tx)
                    db.commit()
                    logger.info(f"Agent {agent_id} hold 决策已记录: reason={decision.reason[:50]}...")
                    continue
                
                if decision.decision.value not in ("buy", "sell"):
                    continue
                
                # 处理股票代码格式：去除.SZ/.SH后缀
                raw_stock_code = decision.stock_code or ""
                stock_code = raw_stock_code.split(".")[0] if "." in raw_stock_code else raw_stock_code
                quantity = decision.quantity
                
                # 从数据库获取股票最新行情（market_data 现在是字符串格式用于提示词）
                stock_data = {}
                quote_model = (
                    db.query(StockQuoteModel)
                    .filter(StockQuoteModel.stock_code == stock_code)
                    .order_by(StockQuoteModel.trade_date.desc())
                    .first()
                )
                if quote_model:
                    stock_data = {
                        "close": float(quote_model.close_price),
                        "prev_close": float(quote_model.prev_close) if quote_model.prev_close else float(quote_model.close_price),
                    }
                    logger.info(f"从数据库获取股票 {stock_code} 行情: close={stock_data['close']}, prev_close={stock_data['prev_close']}")
                
                price = Decimal(str(decision.price or stock_data.get("close", 0)))
                prev_close = Decimal(str(stock_data.get("prev_close", price)))
                
                if not stock_code or not quantity or quantity <= 0 or price <= 0:
                    logger.warning(f"Agent {agent_id} 订单参数无效: stock_code={stock_code}, quantity={quantity}, price={price}")
                    continue
                
                logger.info(f"Agent {agent_id} 准备执行订单: {decision.decision.value} {stock_code} x {quantity} @ {price}")
                
                # 创建订单，关联LLM请求日志
                order = Order(
                    order_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    stock_code=stock_code,
                    side=OrderSide.BUY if decision.decision.value == "buy" else OrderSide.SELL,
                    quantity=quantity,
                    price=price,
                    created_at=tz_now(),
                    status=OrderStatus.PENDING,
                    reason=decision.reason,
                    llm_request_log_id=llm_log_id,  # 关联LLM请求日志
                )
                
                # 处理订单
                order_result = processor.process_order(
                    order=order,
                    portfolio=portfolio,
                    prev_close=prev_close,
                )
                
                if order_result.success:
                    # 保存订单到数据库
                    order_repo.save(order_result.order)
                    
                    # 保存成交记录到数据库
                    if order_result.transaction:
                        tx_repo.save(order_result.transaction)
                    
                    # 更新数据库中的持仓
                    position_repo.delete(agent_id, stock_code)
                    for pos in portfolio.positions:
                        if pos.stock_code == stock_code and pos.shares > 0:
                            position_repo.save(agent_id, pos)
                    
                    executed_orders.append({
                        "stock_code": stock_code,
                        "side": decision.decision.value,
                        "quantity": quantity,
                        "price": float(price),
                    })
                    logger.info(f"Agent {agent_id} 订单执行成功: {decision.decision.value} {stock_code} x {quantity} @ {price}")
                else:
                    logger.warning(f"Agent {agent_id} 订单执行失败 ({stock_code}): {order_result.error_message}")
            
            # 更新数据库中的现金余额（所有订单执行完后）
            if executed_orders:
                portfolio_repo.update_cash(agent_id, portfolio.cash)
                agent.current_cash = portfolio.cash
                repo.save(agent)
                logger.info(f"Agent {agent_id} 共执行 {len(executed_orders)} 个订单，剩余现金: {portfolio.cash}")
        
        return TriggerDecisionResponse(
            success=result.success,
            decision=result.decision.to_dict() if result.decision else None,
            decisions=[d.to_dict() for d in result.decisions] if result.decisions else None,
            executed_count=len(executed_orders) if executed_orders else 0,
            error_message=result.error_message,
            message=f"成功执行 {len(executed_orders)} 个订单" if executed_orders else None,
        )
    except Exception as e:
        logger.exception(f"触发决策失败: {e}")
        
        # 记录异常的决策日志
        from app.db.models import DecisionLogModel
        try:
            error_msg = str(e)
            # 判断是否是API相关错误
            is_api_error = any(keyword in error_msg.lower() for keyword in [
                "timeout", "connection", "api", "llm", "request", "response", "http"
            ])
            
            decision_log = DecisionLogModel(
                agent_id=agent_id,
                status="api_error" if is_api_error else "no_trade",
                error_message=error_msg[:1000],  # 限制长度
            )
            db.add(decision_log)
            db.commit()
            logger.info(f"Agent {agent_id} 异常决策日志已记录: error={error_msg[:100]}")
        except Exception as log_err:
            logger.error(f"记录决策日志失败: {log_err}")
        
        return TriggerDecisionResponse(
            success=False,
            error_message=str(e),
        )
    finally:
        # 释放决策锁
        lock.release()


@router.post(
    "/{agent_id}/pause",
    response_model=AgentResponse,
    summary="暂停Agent",
    description="暂停Agent的自动决策",
    responses={
        404: {"model": ErrorResponse, "description": "Agent不存在"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def pause_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """暂停Agent"""
    repo = ModelAgentRepository(db)
    agent = repo.get_by_id(agent_id)
    
    if agent is None or agent.status == AgentStatus.DELETED:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_NOT_FOUND", "message": f"Agent不存在: {agent_id}"}
        )
    
    repo.update_status(agent_id, AgentStatus.PAUSED)
    
    # 重新获取更新后的Agent
    updated_agent = repo.get_by_id(agent_id)
    return _model_to_response(updated_agent)


@router.post(
    "/{agent_id}/resume",
    response_model=AgentResponse,
    summary="恢复Agent",
    description="恢复Agent的自动决策",
    responses={
        404: {"model": ErrorResponse, "description": "Agent不存在"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def resume_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """恢复Agent"""
    repo = ModelAgentRepository(db)
    agent = repo.get_by_id(agent_id)
    
    if agent is None or agent.status == AgentStatus.DELETED:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_NOT_FOUND", "message": f"Agent不存在: {agent_id}"}
        )
    
    repo.update_status(agent_id, AgentStatus.ACTIVE)
    
    # 重新获取更新后的Agent
    updated_agent = repo.get_by_id(agent_id)
    return _model_to_response(updated_agent)


@router.post(
    "/trigger-all",
    summary="触发所有活跃Agent决策",
    description="并发触发所有活跃状态Agent执行决策",
)
async def trigger_all_decisions(
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """触发所有活跃Agent决策
    
    并发执行所有活跃Agent的决策，每个Agent使用独立的锁防止并发冲突
    """
    import asyncio
    
    repo = ModelAgentRepository(db)
    
    # 获取所有活跃的Agent
    all_agents = repo.get_active()
    
    if not all_agents:
        return {
            "success": True,
            "message": "没有活跃的Agent",
            "total": 0,
            "results": []
        }
    
    # 并发执行所有Agent的决策（每个Agent内部有锁保护）
    async def trigger_single_agent(agent):
        """触发单个Agent决策"""
        try:
            result = await trigger_agent_decision(agent.agent_id, db)
            return {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "success": result.get("success", False),
                "executed_count": result.get("executed_count", 0),
                "error": result.get("error_message")
            }
        except Exception as e:
            logger.exception(f"Agent {agent.agent_id} 决策执行失败: {e}")
            return {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "success": False,
                "error": str(e)
            }
    
    # 并发执行
    tasks = [trigger_single_agent(agent) for agent in all_agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed_results.append({
                "agent_id": all_agents[i].agent_id,
                "agent_name": all_agents[i].name,
                "success": False,
                "error": str(result)
            })
        else:
            processed_results.append(result)
    
    success_count = sum(1 for r in processed_results if r.get("success"))
    
    return {
        "success": True,
        "message": f"批量触发完成: {success_count}/{len(all_agents)} 成功",
        "total": len(all_agents),
        "success_count": success_count,
        "results": processed_results
    }


@router.get(
    "/{agent_id}/decision-logs",
    summary="获取Agent决策日志",
    description="获取指定Agent的决策日志列表",
    responses={
        404: {"model": ErrorResponse, "description": "Agent不存在"},
    },
)
async def get_decision_logs(
    agent_id: str,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    status: str = Query(default=None, description="状态筛选: success, no_trade, api_error"),
    db: Session = Depends(get_db),
):
    """获取Agent决策日志
    
    返回指定Agent的决策日志列表，包含决策状态和错误信息
    """
    from app.db.models import DecisionLogModel
    from app.api.schemas import DecisionLogResponse, DecisionLogListResponse
    
    repo = ModelAgentRepository(db)
    agent = repo.get_by_id(agent_id)
    
    if agent is None or agent.status == AgentStatus.DELETED:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_NOT_FOUND", "message": f"Agent不存在: {agent_id}"}
        )
    
    # 构建查询
    query = db.query(DecisionLogModel).filter(DecisionLogModel.agent_id == agent_id)
    
    if status:
        query = query.filter(DecisionLogModel.status == status)
    
    # 获取总数
    total = query.count()
    
    # 分页查询
    logs = query.order_by(DecisionLogModel.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    # 转换为响应
    items = []
    for log in logs:
        items.append(DecisionLogResponse(
            id=log.id,
            agent_id=log.agent_id,
            agent_name=agent.name,
            llm_model=agent.llm_model,
            parsed_decision=log.parsed_decision,
            status=log.status or "success",
            error_message=log.error_message,
            created_at=log.created_at,
        ))
    
    return DecisionLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/decision-logs/all",
    summary="获取所有决策日志",
    description="获取所有Agent的决策日志列表",
)
async def get_all_decision_logs(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    status: str = Query(default=None, description="状态筛选: success, no_trade, api_error"),
    agent_id: str = Query(default=None, description="Agent ID筛选"),
    db: Session = Depends(get_db),
):
    """获取所有决策日志
    
    返回所有Agent的决策日志列表
    """
    from app.db.models import DecisionLogModel, ModelAgentModel
    from app.api.schemas import DecisionLogResponse, DecisionLogListResponse
    
    # 构建查询
    query = db.query(DecisionLogModel, ModelAgentModel).join(
        ModelAgentModel, DecisionLogModel.agent_id == ModelAgentModel.agent_id
    )
    
    if status:
        query = query.filter(DecisionLogModel.status == status)
    
    if agent_id:
        query = query.filter(DecisionLogModel.agent_id == agent_id)
    
    # 获取总数
    total = query.count()
    
    # 分页查询
    results = query.order_by(DecisionLogModel.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    # 转换为响应
    items = []
    for log, agent in results:
        items.append(DecisionLogResponse(
            id=log.id,
            agent_id=log.agent_id,
            agent_name=agent.name if agent else None,
            llm_model=agent.llm_model if agent else None,
            parsed_decision=log.parsed_decision,
            status=log.status or "success",
            error_message=log.error_message,
            created_at=log.created_at,
        ))
    
    return DecisionLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )
