"""数据仓库实现 - Portfolio和Position的CRUD操作"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.models import (
    ModelAgentModel,
    PositionModel,
    OrderModel,
    TransactionModel,
    LLMProviderModel,
)
from app.models.entities import (
    Portfolio,
    Position,
    ModelAgent,
    Order,
    Transaction,
    TradingFees,
    LLMProvider,
)
from app.models.enums import OrderSide, OrderStatus, AgentStatus, LLMProtocol


class PositionRepository:
    """持仓数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_agent_and_stock(
        self, agent_id: str, stock_code: str
    ) -> Optional[Position]:
        """根据agent_id和stock_code获取持仓"""
        position_model = (
            self.db.query(PositionModel)
            .filter(
                and_(
                    PositionModel.agent_id == agent_id,
                    PositionModel.stock_code == stock_code,
                )
            )
            .first()
        )
        if position_model:
            return self._to_entity(position_model)
        return None

    def get_all_by_agent(self, agent_id: str) -> List[Position]:
        """获取agent的所有持仓"""
        position_models = (
            self.db.query(PositionModel)
            .filter(PositionModel.agent_id == agent_id)
            .all()
        )
        return [self._to_entity(p) for p in position_models]

    def save(self, agent_id: str, position: Position) -> None:
        """保存或更新持仓"""
        existing = (
            self.db.query(PositionModel)
            .filter(
                and_(
                    PositionModel.agent_id == agent_id,
                    PositionModel.stock_code == position.stock_code,
                )
            )
            .first()
        )

        if existing:
            existing.shares = position.shares
            existing.avg_cost = position.avg_cost
            existing.buy_date = datetime.strptime(position.buy_date, "%Y-%m-%d").date()
        else:
            new_position = PositionModel(
                agent_id=agent_id,
                stock_code=position.stock_code,
                shares=position.shares,
                avg_cost=position.avg_cost,
                buy_date=datetime.strptime(position.buy_date, "%Y-%m-%d").date(),
            )
            self.db.add(new_position)

        self.db.commit()

    def delete(self, agent_id: str, stock_code: str) -> bool:
        """删除持仓"""
        result = (
            self.db.query(PositionModel)
            .filter(
                and_(
                    PositionModel.agent_id == agent_id,
                    PositionModel.stock_code == stock_code,
                )
            )
            .delete()
        )
        self.db.commit()
        return result > 0

    def delete_all_by_agent(self, agent_id: str) -> int:
        """删除agent的所有持仓"""
        result = (
            self.db.query(PositionModel)
            .filter(PositionModel.agent_id == agent_id)
            .delete()
        )
        self.db.commit()
        return result

    def _to_entity(self, model: PositionModel) -> Position:
        """将ORM模型转换为实体"""
        return Position(
            stock_code=model.stock_code,
            shares=model.shares,
            avg_cost=Decimal(str(model.avg_cost)),
            buy_date=model.buy_date.strftime("%Y-%m-%d"),
        )


class PortfolioRepository:
    """投资组合数据仓库"""

    def __init__(self, db: Session):
        self.db = db
        self.position_repo = PositionRepository(db)

    def get_by_agent_id(self, agent_id: str) -> Optional[Portfolio]:
        """根据agent_id获取投资组合"""
        agent_model = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .first()
        )
        if not agent_model:
            return None

        positions = self.position_repo.get_all_by_agent(agent_id)
        return Portfolio(
            agent_id=agent_id,
            cash=Decimal(str(agent_model.current_cash)),
            positions=positions,
        )

    def update_cash(self, agent_id: str, new_cash: Decimal) -> bool:
        """更新现金余额"""
        result = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .update({"current_cash": new_cash})
        )
        self.db.commit()
        return result > 0

    def add_cash(self, agent_id: str, delta: Decimal) -> Optional[Decimal]:
        """增加或减少现金（delta可为负数）"""
        agent_model = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .first()
        )
        if not agent_model:
            return None

        new_cash = Decimal(str(agent_model.current_cash)) + delta
        agent_model.current_cash = new_cash
        self.db.commit()
        return new_cash

    def get_cash(self, agent_id: str) -> Optional[Decimal]:
        """获取现金余额"""
        agent_model = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .first()
        )
        if agent_model:
            return Decimal(str(agent_model.current_cash))
        return None

    def get_initial_cash(self, agent_id: str) -> Optional[Decimal]:
        """获取初始资金"""
        agent_model = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .first()
        )
        if agent_model:
            return Decimal(str(agent_model.initial_cash))
        return None


class ModelAgentRepository:
    """模型代理数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, agent_id: str) -> Optional[ModelAgent]:
        """根据ID获取Agent"""
        model = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .first()
        )
        if model:
            return self._to_entity(model)
        return None

    def get_all(self) -> List[ModelAgent]:
        """获取所有Agent"""
        models = self.db.query(ModelAgentModel).all()
        return [self._to_entity(m) for m in models]

    def get_active(self) -> List[ModelAgent]:
        """获取所有活跃的Agent"""
        models = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.status == AgentStatus.ACTIVE.value)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def save(self, agent: ModelAgent) -> None:
        """保存或更新Agent"""
        existing = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent.agent_id)
            .first()
        )

        if existing:
            existing.name = agent.name
            existing.initial_cash = agent.initial_cash
            existing.current_cash = agent.current_cash
            existing.template_id = agent.template_id
            existing.provider_id = agent.provider_id
            existing.llm_model = agent.llm_model
            existing.status = agent.status.value
            existing.schedule_type = agent.schedule_type
        else:
            new_agent = ModelAgentModel(
                agent_id=agent.agent_id,
                name=agent.name,
                initial_cash=agent.initial_cash,
                current_cash=agent.current_cash or agent.initial_cash,
                template_id=agent.template_id,
                provider_id=agent.provider_id,
                llm_model=agent.llm_model,
                status=agent.status.value,
                schedule_type=agent.schedule_type,
            )
            self.db.add(new_agent)

        self.db.commit()

    def delete(self, agent_id: str) -> bool:
        """删除Agent（软删除，设置状态为deleted）"""
        result = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .update({"status": AgentStatus.DELETED.value})
        )
        self.db.commit()
        return result > 0

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        """更新Agent状态"""
        result = (
            self.db.query(ModelAgentModel)
            .filter(ModelAgentModel.agent_id == agent_id)
            .update({"status": status.value})
        )
        self.db.commit()
        return result > 0

    def _to_entity(self, model: ModelAgentModel) -> ModelAgent:
        """将ORM模型转换为实体"""
        return ModelAgent(
            agent_id=model.agent_id,
            name=model.name,
            initial_cash=Decimal(str(model.initial_cash)),
            template_id=model.template_id or "",
            provider_id=model.provider_id or "",
            llm_model=model.llm_model,
            created_at=model.created_at,
            status=AgentStatus(model.status),
            current_cash=Decimal(str(model.current_cash)),
            schedule_type=model.schedule_type or "daily",
            updated_at=model.updated_at,
        )


class OrderRepository:
    """订单数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def save(self, order: Order) -> None:
        """保存或更新订单"""
        existing = (
            self.db.query(OrderModel)
            .filter(OrderModel.order_id == order.order_id)
            .first()
        )

        if existing:
            existing.stock_code = order.stock_code
            existing.side = order.side.value
            existing.quantity = order.quantity
            existing.price = order.price
            existing.status = order.status.value
            existing.reject_reason = order.reject_reason
            existing.reason = order.reason
            existing.llm_request_log_id = order.llm_request_log_id
        else:
            new_order = OrderModel(
                order_id=order.order_id,
                agent_id=order.agent_id,
                llm_request_log_id=order.llm_request_log_id,
                stock_code=order.stock_code,
                side=order.side.value,
                quantity=order.quantity,
                price=order.price,
                status=order.status.value,
                reject_reason=order.reject_reason,
                reason=order.reason,
            )
            self.db.add(new_order)

        self.db.commit()

    def get_by_id(self, order_id: str) -> Optional[Order]:
        """根据ID获取订单"""
        model = (
            self.db.query(OrderModel)
            .filter(OrderModel.order_id == order_id)
            .first()
        )
        if model:
            return self._to_entity(model)
        return None

    def get_by_agent(
        self,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
        status: Optional[OrderStatus] = None,
    ) -> List[Order]:
        """获取agent的订单列表"""
        query = (
            self.db.query(OrderModel)
            .filter(OrderModel.agent_id == agent_id)
        )
        
        if status:
            query = query.filter(OrderModel.status == status.value)
        
        models = (
            query
            .order_by(OrderModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def get_by_agent_and_stock(
        self,
        agent_id: str,
        stock_code: str,
        limit: int = 100,
    ) -> List[Order]:
        """获取agent对某只股票的订单"""
        models = (
            self.db.query(OrderModel)
            .filter(
                and_(
                    OrderModel.agent_id == agent_id,
                    OrderModel.stock_code == stock_code,
                )
            )
            .order_by(OrderModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def get_by_date_range(
        self,
        agent_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Order]:
        """获取指定日期范围内的订单"""
        models = (
            self.db.query(OrderModel)
            .filter(
                and_(
                    OrderModel.agent_id == agent_id,
                    OrderModel.created_at >= start_date,
                    OrderModel.created_at <= end_date,
                )
            )
            .order_by(OrderModel.created_at.desc())
            .all()
        )
        return [self._to_entity(m) for m in models]

    def update_status(
        self,
        order_id: str,
        status: OrderStatus,
        reject_reason: Optional[str] = None,
    ) -> bool:
        """更新订单状态"""
        update_data = {"status": status.value}
        if reject_reason:
            update_data["reject_reason"] = reject_reason
        
        result = (
            self.db.query(OrderModel)
            .filter(OrderModel.order_id == order_id)
            .update(update_data)
        )
        self.db.commit()
        return result > 0

    def count_by_agent(
        self,
        agent_id: str,
        status: Optional[OrderStatus] = None,
    ) -> int:
        """统计agent的订单数量"""
        query = (
            self.db.query(OrderModel)
            .filter(OrderModel.agent_id == agent_id)
        )
        
        if status:
            query = query.filter(OrderModel.status == status.value)
        
        return query.count()

    def _to_entity(self, model: OrderModel) -> Order:
        """将ORM模型转换为实体"""
        return Order(
            order_id=model.order_id,
            agent_id=model.agent_id,
            stock_code=model.stock_code,
            side=OrderSide(model.side),
            quantity=model.quantity,
            price=Decimal(str(model.price)) if model.price is not None else Decimal("0"),
            created_at=model.created_at,
            status=OrderStatus(model.status),
            reject_reason=model.reject_reason,
            reason=model.reason,
            llm_request_log_id=model.llm_request_log_id,
        )


class TransactionRepository:
    """成交记录数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def save(self, transaction: Transaction) -> None:
        """保存成交记录"""
        existing = (
            self.db.query(TransactionModel)
            .filter(TransactionModel.tx_id == transaction.tx_id)
            .first()
        )

        if existing:
            # 成交记录通常不更新，但保留更新逻辑以防万一
            existing.stock_code = transaction.stock_code
            existing.side = transaction.side.value
            existing.quantity = transaction.quantity
            existing.price = transaction.price
            existing.commission = transaction.fees.commission
            existing.stamp_tax = transaction.fees.stamp_tax
            existing.transfer_fee = transaction.fees.transfer_fee
        else:
            new_tx = TransactionModel(
                tx_id=transaction.tx_id,
                order_id=transaction.order_id,
                agent_id=transaction.agent_id,
                stock_code=transaction.stock_code,
                side=transaction.side.value,
                quantity=transaction.quantity,
                price=transaction.price,
                commission=transaction.fees.commission,
                stamp_tax=transaction.fees.stamp_tax,
                transfer_fee=transaction.fees.transfer_fee,
            )
            self.db.add(new_tx)

        self.db.commit()

    def get_by_id(self, tx_id: str) -> Optional[Transaction]:
        """根据ID获取成交记录"""
        model = (
            self.db.query(TransactionModel)
            .filter(TransactionModel.tx_id == tx_id)
            .first()
        )
        if model:
            return self._to_entity(model)
        return None

    def get_by_order_id(self, order_id: str) -> Optional[Transaction]:
        """根据订单ID获取成交记录"""
        model = (
            self.db.query(TransactionModel)
            .filter(TransactionModel.order_id == order_id)
            .first()
        )
        if model:
            return self._to_entity(model)
        return None

    def get_by_agent(
        self,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
        side: Optional[OrderSide] = None,
    ) -> List[Transaction]:
        """获取agent的成交记录列表"""
        query = (
            self.db.query(TransactionModel)
            .filter(TransactionModel.agent_id == agent_id)
        )
        
        if side:
            query = query.filter(TransactionModel.side == side.value)
        
        models = (
            query
            .order_by(TransactionModel.executed_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def get_by_agent_and_stock(
        self,
        agent_id: str,
        stock_code: str,
        limit: int = 100,
    ) -> List[Transaction]:
        """获取agent对某只股票的成交记录"""
        models = (
            self.db.query(TransactionModel)
            .filter(
                and_(
                    TransactionModel.agent_id == agent_id,
                    TransactionModel.stock_code == stock_code,
                )
            )
            .order_by(TransactionModel.executed_at.desc())
            .limit(limit)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def get_by_date_range(
        self,
        agent_id: str,
        start_date: datetime,
        end_date: datetime,
        stock_code: Optional[str] = None,
        side: Optional[OrderSide] = None,
    ) -> List[Transaction]:
        """获取指定日期范围内的成交记录
        
        支持按时间范围、股票代码、交易方向筛选
        """
        query = (
            self.db.query(TransactionModel)
            .filter(
                and_(
                    TransactionModel.agent_id == agent_id,
                    TransactionModel.executed_at >= start_date,
                    TransactionModel.executed_at <= end_date,
                )
            )
        )
        
        if stock_code:
            query = query.filter(TransactionModel.stock_code == stock_code)
        
        if side:
            query = query.filter(TransactionModel.side == side.value)
        
        models = (
            query
            .order_by(TransactionModel.executed_at.desc())
            .all()
        )
        return [self._to_entity(m) for m in models]

    def count_by_agent(
        self,
        agent_id: str,
        side: Optional[OrderSide] = None,
    ) -> int:
        """统计agent的成交记录数量"""
        query = (
            self.db.query(TransactionModel)
            .filter(TransactionModel.agent_id == agent_id)
        )
        
        if side:
            query = query.filter(TransactionModel.side == side.value)
        
        return query.count()

    def get_total_fees_by_agent(self, agent_id: str) -> TradingFees:
        """获取agent的累计交易费用"""
        from sqlalchemy import func
        
        result = (
            self.db.query(
                func.sum(TransactionModel.commission).label("commission"),
                func.sum(TransactionModel.stamp_tax).label("stamp_tax"),
                func.sum(TransactionModel.transfer_fee).label("transfer_fee"),
            )
            .filter(TransactionModel.agent_id == agent_id)
            .first()
        )
        
        return TradingFees(
            commission=Decimal(str(result.commission or 0)),
            stamp_tax=Decimal(str(result.stamp_tax or 0)),
            transfer_fee=Decimal(str(result.transfer_fee or 0)),
        )

    def _to_entity(self, model: TransactionModel) -> Transaction:
        """将ORM模型转换为实体"""
        fees = TradingFees(
            commission=Decimal(str(model.commission)) if model.commission is not None else Decimal("0"),
            stamp_tax=Decimal(str(model.stamp_tax)) if model.stamp_tax is not None else Decimal("0"),
            transfer_fee=Decimal(str(model.transfer_fee)) if model.transfer_fee is not None else Decimal("0"),
        )
        
        return Transaction(
            tx_id=model.tx_id,
            order_id=model.order_id,
            agent_id=model.agent_id,
            stock_code=model.stock_code,
            side=OrderSide(model.side),
            quantity=model.quantity,
            price=Decimal(str(model.price)) if model.price is not None else Decimal("0"),
            fees=fees,
            executed_at=model.executed_at,
        )


class LLMProviderRepository:
    """LLM渠道数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, provider_id: str) -> Optional[LLMProvider]:
        """根据ID获取LLM渠道"""
        model = (
            self.db.query(LLMProviderModel)
            .filter(LLMProviderModel.provider_id == provider_id)
            .first()
        )
        if model:
            return self._to_entity(model)
        return None

    def get_all(self) -> List[LLMProvider]:
        """获取所有LLM渠道"""
        models = self.db.query(LLMProviderModel).all()
        return [self._to_entity(m) for m in models]

    def get_all_active(self) -> List[LLMProvider]:
        """获取所有活跃的LLM渠道"""
        models = (
            self.db.query(LLMProviderModel)
            .filter(LLMProviderModel.is_active == 1)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def _to_entity(self, model: LLMProviderModel) -> LLMProvider:
        """将ORM模型转换为实体"""
        return LLMProvider(
            provider_id=model.provider_id,
            name=model.name,
            protocol=LLMProtocol(model.protocol),
            api_url=model.api_url,
            api_key=model.api_key,
            is_active=bool(model.is_active),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
