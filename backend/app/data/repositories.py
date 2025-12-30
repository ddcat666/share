"""数据采集模块的数据仓库实现"""

import logging
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.db.models import StockQuoteModel, SentimentScoreModel
from app.models.entities import StockQuote

logger = logging.getLogger(__name__)


class StockQuoteRepository:
    """股票行情数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def upsert(self, quote: StockQuote) -> bool:
        """更新或插入行情数据（幂等性存储）
        
        如果(stock_code, trade_date)组合已存在，则更新数据；
        否则插入新记录。
        
        Args:
            quote: 股票行情数据
            
        Returns:
            True表示成功，False表示失败
        """
        try:
            trade_date = self._parse_date(quote.trade_date)
            
            existing = (
                self.db.query(StockQuoteModel)
                .filter(
                    and_(
                        StockQuoteModel.stock_code == quote.stock_code,
                        StockQuoteModel.trade_date == trade_date,
                    )
                )
                .first()
            )
            
            if existing:
                # 更新现有记录
                existing.open_price = quote.open_price
                existing.high_price = quote.high_price
                existing.low_price = quote.low_price
                existing.close_price = quote.close_price
                existing.prev_close = quote.prev_close
                existing.volume = quote.volume
                existing.amount = quote.amount
                if quote.stock_name:
                    existing.stock_name = quote.stock_name
                logger.debug(
                    f"Updated quote for {quote.stock_code} on {quote.trade_date}"
                )
            else:
                # 插入新记录
                new_quote = StockQuoteModel(
                    stock_code=quote.stock_code,
                    stock_name=quote.stock_name,
                    trade_date=trade_date,
                    open_price=quote.open_price,
                    high_price=quote.high_price,
                    low_price=quote.low_price,
                    close_price=quote.close_price,
                    prev_close=quote.prev_close,
                    volume=quote.volume,
                    amount=quote.amount,
                )
                self.db.add(new_quote)
                self.db.flush()  # Flush to get the ID without committing
                logger.debug(
                    f"Inserted quote for {quote.stock_code} on {quote.trade_date}"
                )
            
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to upsert quote: {e}")
            self.db.rollback()
            return False
    
    def upsert_batch(self, quotes: List[StockQuote]) -> Tuple[int, int]:
        """批量更新或插入行情数据
        
        Args:
            quotes: 股票行情数据列表
            
        Returns:
            (成功数量, 失败数量)
        """
        success_count = 0
        fail_count = 0
        
        for quote in quotes:
            if self.upsert(quote):
                success_count += 1
            else:
                fail_count += 1
        
        logger.info(
            f"Batch upsert completed: {success_count} success, {fail_count} failed"
        )
        return success_count, fail_count
    
    def get_by_code_and_date(
        self,
        stock_code: str,
        trade_date: str,
    ) -> Optional[StockQuote]:
        """根据股票代码和日期获取行情数据
        
        Args:
            stock_code: 股票代码
            trade_date: 交易日期 (YYYY-MM-DD)
            
        Returns:
            股票行情数据，不存在则返回None
        """
        date_obj = self._parse_date(trade_date)
        
        model = (
            self.db.query(StockQuoteModel)
            .filter(
                and_(
                    StockQuoteModel.stock_code == stock_code,
                    StockQuoteModel.trade_date == date_obj,
                )
            )
            .first()
        )
        
        if model:
            return self._to_entity(model)
        return None
    
    def get_history(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> List[StockQuote]:
        """获取历史行情数据
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            
        Returns:
            股票行情数据列表
        """
        start = self._parse_date(start_date)
        end = self._parse_date(end_date)
        
        models = (
            self.db.query(StockQuoteModel)
            .filter(
                and_(
                    StockQuoteModel.stock_code == stock_code,
                    StockQuoteModel.trade_date >= start,
                    StockQuoteModel.trade_date <= end,
                )
            )
            .order_by(StockQuoteModel.trade_date.asc())
            .all()
        )
        
        return [self._to_entity(m) for m in models]
    
    def get_latest(self, stock_code: str) -> Optional[StockQuote]:
        """获取最新行情数据
        
        Args:
            stock_code: 股票代码
            
        Returns:
            最新的股票行情数据
        """
        model = (
            self.db.query(StockQuoteModel)
            .filter(StockQuoteModel.stock_code == stock_code)
            .order_by(StockQuoteModel.trade_date.desc())
            .first()
        )
        
        if model:
            return self._to_entity(model)
        return None
    
    def count_by_code(self, stock_code: str) -> int:
        """统计某只股票的行情记录数量
        
        Args:
            stock_code: 股票代码
            
        Returns:
            记录数量
        """
        return (
            self.db.query(StockQuoteModel)
            .filter(StockQuoteModel.stock_code == stock_code)
            .count()
        )
    
    def get_all_latest(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> Tuple[List[dict], int]:
        """获取所有股票的最新行情数据（每只股票取最新一条）
        
        Args:
            page: 页码
            page_size: 每页数量
            search: 搜索关键词（股票代码）
            
        Returns:
            (行情数据列表, 总数)
        """
        from sqlalchemy import func as sql_func, case
        
        # 子查询：获取每只股票的最新日期
        subquery = (
            self.db.query(
                StockQuoteModel.stock_code,
                sql_func.max(StockQuoteModel.trade_date).label("max_date")
            )
            .group_by(StockQuoteModel.stock_code)
            .subquery()
        )
        
        # 主查询：关联获取最新记录
        query = (
            self.db.query(StockQuoteModel)
            .join(
                subquery,
                and_(
                    StockQuoteModel.stock_code == subquery.c.stock_code,
                    StockQuoteModel.trade_date == subquery.c.max_date,
                )
            )
        )
        
        # 搜索过滤（支持股票代码和股票名称）
        if search:
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    StockQuoteModel.stock_code.like(f"%{search}%"),
                    StockQuoteModel.stock_name.like(f"%{search}%")
                )
            )
        
        # 获取总数
        total = query.count()
        
        # 计算涨跌幅并排序（涨跌幅降序 + 创建时间降序）
        change_pct = case(
            (StockQuoteModel.prev_close > 0, 
             (StockQuoteModel.close_price - StockQuoteModel.prev_close) / StockQuoteModel.prev_close * 100),
            else_=0
        )
        
        # 分页
        offset = (page - 1) * page_size
        models = (
            query
            .order_by(change_pct.desc(), StockQuoteModel.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        
        # 获取每只股票的记录总数
        result = []
        for model in models:
            count = self.count_by_code(model.stock_code)
            prev_close = float(model.prev_close) if model.prev_close else 0
            close_price = float(model.close_price) if model.close_price else 0
            change_pct_val = ((close_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
            
            result.append({
                "stock_code": model.stock_code,
                "stock_name": model.stock_name,
                "trade_date": model.trade_date.strftime("%Y-%m-%d"),
                "open_price": float(model.open_price),
                "high_price": float(model.high_price),
                "low_price": float(model.low_price),
                "close_price": float(model.close_price),
                "prev_close": float(model.prev_close),
                "change_pct": round(change_pct_val, 2),
                "volume": model.volume,
                "amount": float(model.amount),
                "created_at": model.created_at.strftime("%Y-%m-%d %H:%M:%S") if model.created_at else None,
                "record_count": count,
            })
        
        return result, total
    
    def delete_by_code_and_date(
        self,
        stock_code: str,
        trade_date: str,
    ) -> bool:
        """删除指定的行情记录
        
        Args:
            stock_code: 股票代码
            trade_date: 交易日期 (YYYY-MM-DD)
            
        Returns:
            True表示删除成功，False表示记录不存在
        """
        date_obj = self._parse_date(trade_date)
        
        result = (
            self.db.query(StockQuoteModel)
            .filter(
                and_(
                    StockQuoteModel.stock_code == stock_code,
                    StockQuoteModel.trade_date == date_obj,
                )
            )
            .delete()
        )
        
        self.db.commit()
        return result > 0
    
    def get_all_by_code(
        self,
        stock_code: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[dict], int]:
        """获取某只股票的所有历史行情数据
        
        Args:
            stock_code: 股票代码
            page: 页码
            page_size: 每页数量
            
        Returns:
            (行情数据列表, 总数)
        """
        # 获取总数
        total = (
            self.db.query(StockQuoteModel)
            .filter(StockQuoteModel.stock_code == stock_code)
            .count()
        )
        
        # 分页查询，按交易日期倒序
        offset = (page - 1) * page_size
        models = (
            self.db.query(StockQuoteModel)
            .filter(StockQuoteModel.stock_code == stock_code)
            .order_by(StockQuoteModel.trade_date.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        
        result = []
        for model in models:
            prev_close = float(model.prev_close) if model.prev_close else 0
            close_price = float(model.close_price) if model.close_price else 0
            change_pct = ((close_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
            
            result.append({
                "stock_code": model.stock_code,
                "stock_name": model.stock_name,
                "trade_date": model.trade_date.strftime("%Y-%m-%d"),
                "open_price": float(model.open_price),
                "high_price": float(model.high_price),
                "low_price": float(model.low_price),
                "close_price": float(model.close_price),
                "prev_close": float(model.prev_close),
                "change_pct": round(change_pct, 2),
                "volume": model.volume,
                "amount": float(model.amount),
                "created_at": model.created_at.strftime("%Y-%m-%d %H:%M:%S") if model.created_at else None,
            })
        
        return result, total
    
    def _parse_date(self, date_str: str) -> date:
        """解析日期字符串"""
        if isinstance(date_str, date):
            return date_str
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    
    def _to_entity(self, model: StockQuoteModel) -> StockQuote:
        """将ORM模型转换为实体"""
        return StockQuote(
            stock_code=model.stock_code,
            trade_date=model.trade_date.strftime("%Y-%m-%d"),
            open_price=Decimal(str(model.open_price)),
            high_price=Decimal(str(model.high_price)),
            low_price=Decimal(str(model.low_price)),
            close_price=Decimal(str(model.close_price)),
            prev_close=Decimal(str(model.prev_close)),
            volume=model.volume,
            amount=Decimal(str(model.amount)),
        )


class SentimentScoreRepository:
    """情绪分数数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def save(
        self,
        stock_code: Optional[str],
        score: float,
        source: Optional[str] = None,
    ) -> bool:
        """保存情绪分数
        
        Args:
            stock_code: 股票代码（可选，None表示市场整体情绪）
            score: 情绪分数 (-1.0 到 +1.0)
            source: 数据来源
            
        Returns:
            True表示成功
        """
        try:
            model = SentimentScoreModel(
                stock_code=stock_code,
                score=Decimal(str(score)),
                source=source,
            )
            self.db.add(model)
            self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save sentiment score: {e}")
            self.db.rollback()
            return False
    
    def get_latest(self, stock_code: Optional[str] = None) -> Optional[float]:
        """获取最新情绪分数
        
        Args:
            stock_code: 股票代码（可选）
            
        Returns:
            情绪分数
        """
        query = self.db.query(SentimentScoreModel)
        
        if stock_code:
            query = query.filter(SentimentScoreModel.stock_code == stock_code)
        
        model = query.order_by(SentimentScoreModel.analyzed_at.desc()).first()
        
        if model:
            return float(model.score)
        return None
    
    def get_history(
        self,
        stock_code: Optional[str],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Tuple[datetime, float]]:
        """获取历史情绪分数
        
        Args:
            stock_code: 股票代码（可选）
            start_time: 开始时间
            end_time: 结束时间
            
        Returns:
            (时间, 分数) 列表
        """
        query = self.db.query(SentimentScoreModel).filter(
            and_(
                SentimentScoreModel.analyzed_at >= start_time,
                SentimentScoreModel.analyzed_at <= end_time,
            )
        )
        
        if stock_code:
            query = query.filter(SentimentScoreModel.stock_code == stock_code)
        
        models = query.order_by(SentimentScoreModel.analyzed_at.asc()).all()
        
        return [(m.analyzed_at, float(m.score)) for m in models]



class MarketDataRepository:
    """市场数据仓库
    
    存储和获取市场情绪、大盘概况、热门股票等数据
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def upsert(
        self,
        data_type: str,
        data_content: dict,
        data_date: date,
    ) -> bool:
        """更新或插入市场数据
        
        Args:
            data_type: 数据类型 (market_sentiment, index_overview, hot_stocks)
            data_content: 数据内容（字典）
            data_date: 数据日期
            
        Returns:
            True表示成功
        """
        from app.db.models import MarketDataModel
        
        try:
            existing = (
                self.db.query(MarketDataModel)
                .filter(
                    and_(
                        MarketDataModel.data_type == data_type,
                        MarketDataModel.data_date == data_date,
                    )
                )
                .first()
            )
            
            if existing:
                existing.data_content = data_content
                logger.debug(f"Updated market data: {data_type} for {data_date}")
            else:
                new_data = MarketDataModel(
                    data_type=data_type,
                    data_content=data_content,
                    data_date=data_date,
                )
                self.db.add(new_data)
                logger.debug(f"Inserted market data: {data_type} for {data_date}")
            
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to upsert market data: {e}")
            self.db.rollback()
            return False
    
    def get_latest(self, data_type: str) -> Optional[dict]:
        """获取最新的市场数据
        
        Args:
            data_type: 数据类型
            
        Returns:
            数据内容字典，不存在则返回None
        """
        from app.db.models import MarketDataModel
        
        model = (
            self.db.query(MarketDataModel)
            .filter(MarketDataModel.data_type == data_type)
            .order_by(MarketDataModel.data_date.desc())
            .first()
        )
        
        if model:
            return {
                "data": model.data_content,
                "date": model.data_date.strftime("%Y-%m-%d"),
                "updated_at": model.updated_at.strftime("%Y-%m-%d %H:%M:%S") if model.updated_at else None,
            }
        return None
    
    def get_by_date(self, data_type: str, data_date: date) -> Optional[dict]:
        """获取指定日期的市场数据
        
        Args:
            data_type: 数据类型
            data_date: 数据日期
            
        Returns:
            数据内容字典
        """
        from app.db.models import MarketDataModel
        
        model = (
            self.db.query(MarketDataModel)
            .filter(
                and_(
                    MarketDataModel.data_type == data_type,
                    MarketDataModel.data_date == data_date,
                )
            )
            .first()
        )
        
        if model:
            return model.data_content
        return None
    
    def get_all_latest(self) -> dict:
        """获取所有类型的最新市场数据
        
        Returns:
            {data_type: data_content} 字典
        """
        from app.db.models import MarketDataModel
        from sqlalchemy import func as sql_func
        
        # 获取每种类型的最新记录
        subquery = (
            self.db.query(
                MarketDataModel.data_type,
                sql_func.max(MarketDataModel.data_date).label("max_date")
            )
            .group_by(MarketDataModel.data_type)
            .subquery()
        )
        
        models = (
            self.db.query(MarketDataModel)
            .join(
                subquery,
                and_(
                    MarketDataModel.data_type == subquery.c.data_type,
                    MarketDataModel.data_date == subquery.c.max_date,
                )
            )
            .all()
        )
        
        result = {}
        for model in models:
            result[model.data_type] = {
                "data": model.data_content,
                "date": model.data_date.strftime("%Y-%m-%d"),
                "updated_at": model.updated_at.strftime("%Y-%m-%d %H:%M:%S") if model.updated_at else None,
            }
        
        return result
