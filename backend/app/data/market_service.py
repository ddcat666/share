"""市场数据服务

提供市场情绪、大盘概况、热门股票等数据的获取和刷新功能

职责：
- 市场情绪计算
- 大盘指数概况
- 热门股票统计（不负责存储行情，委托给 QuoteService）
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from sqlalchemy.orm import Session

from app.data.repositories import MarketDataRepository
from app.data.collector import AKShareDataCollector
from app.core.timezone import now_str, today_str

if TYPE_CHECKING:
    from app.data.quote_service import QuoteService

logger = logging.getLogger(__name__)

# 禁用 AKShare 的 tqdm 进度条
import os
os.environ["AKSHARE_TQDM"] = "0"


class MarketDataService:
    """市场数据服务
    
    职责：
    - 市场情绪计算
    - 大盘指数概况
    - 热门股票统计（不负责存储行情）
    """
    
    # 数据类型常量
    TYPE_MARKET_SENTIMENT = "market_sentiment"
    TYPE_INDEX_OVERVIEW = "index_overview"
    TYPE_HOT_STOCKS = "hot_stocks"
    
    def __init__(self, db: Session, quote_service: "QuoteService" = None):
        """初始化市场数据服务
        
        Args:
            db: 数据库会话
            quote_service: 行情服务实例（用于委托行情存储）
        """
        self.db = db
        self.market_repo = MarketDataRepository(db)
        self.quote_service = quote_service  # 委托行情存储
        self.collector = AKShareDataCollector()
    
    async def refresh_all(self) -> Dict[str, bool]:
        """刷新所有市场数据
        
        优化：只调用一次 stock_zh_a_spot_em，共享数据给多个处理函数
        
        Returns:
            {data_type: success} 字典
        """
        results = {}
        
        # 一次性获取 A 股实时行情数据（避免重复调用）
        spot_df = None
        try:
            ak = self.collector._get_ak()
            spot_df = ak.stock_zh_a_spot_em()
            logger.info(f"Fetched {len(spot_df) if spot_df is not None else 0} stocks from A-share spot data")
        except Exception as e:
            logger.error(f"Failed to fetch A-share spot data: {e}")
        
        # 使用共享数据刷新各项指标
        results[self.TYPE_MARKET_SENTIMENT] = await self._refresh_market_sentiment_with_data(spot_df)
        results[self.TYPE_INDEX_OVERVIEW] = await self.refresh_index_overview()
        # 保存所有股票数据（不限制数量）
        results[self.TYPE_HOT_STOCKS] = await self._refresh_hot_stocks_with_data(spot_df, limit=None)
        
        logger.info(f"Market data refresh completed: {results}")
        return results
    
    async def refresh_market_sentiment(self) -> bool:
        """刷新市场情绪数据（单独调用时）
        
        Returns:
            是否成功
        """
        try:
            ak = self.collector._get_ak()
            df = ak.stock_zh_a_spot_em()
            return await self._refresh_market_sentiment_with_data(df)
        except Exception as e:
            logger.error(f"Failed to refresh market sentiment: {e}")
            return False
    
    async def _refresh_market_sentiment_with_data(self, df) -> bool:
        """使用已获取的数据刷新市场情绪
        
        Args:
            df: A股实时行情 DataFrame
            
        Returns:
            是否成功
        """
        try:
            sentiment_data = {
                "fear_greed_index": 50,
                "market_mood": "中性",
                "trading_activity": "正常",
                "volatility": "低",
            }
            
            if df is not None and not df.empty:
                # 计算涨跌家数
                up_count = len(df[df["涨跌幅"] > 0])
                down_count = len(df[df["涨跌幅"] < 0])
                flat_count = len(df[df["涨跌幅"] == 0])
                total = len(df)
                
                # 计算情绪指数 (0-100)
                if total > 0:
                    fear_greed = int((up_count / total) * 100)
                    sentiment_data["fear_greed_index"] = fear_greed
                    
                    if fear_greed >= 70:
                        sentiment_data["market_mood"] = "极度贪婪"
                    elif fear_greed >= 55:
                        sentiment_data["market_mood"] = "偏乐观"
                    elif fear_greed >= 45:
                        sentiment_data["market_mood"] = "中性"
                    elif fear_greed >= 30:
                        sentiment_data["market_mood"] = "偏悲观"
                    else:
                        sentiment_data["market_mood"] = "极度恐惧"
                
                sentiment_data["up_count"] = up_count
                sentiment_data["down_count"] = down_count
                sentiment_data["flat_count"] = flat_count
                sentiment_data["total_count"] = total
                
                # 计算涨停跌停数
                limit_up = len(df[df["涨跌幅"] >= 9.9])
                limit_down = len(df[df["涨跌幅"] <= -9.9])
                sentiment_data["limit_up_count"] = limit_up
                sentiment_data["limit_down_count"] = limit_down
                
                # 判断交易活跃度
                avg_turnover = df["换手率"].mean() if "换手率" in df.columns else 0
                if avg_turnover > 5:
                    sentiment_data["trading_activity"] = "活跃"
                elif avg_turnover > 2:
                    sentiment_data["trading_activity"] = "正常"
                else:
                    sentiment_data["trading_activity"] = "低迷"
            
            sentiment_data["updated_at"] = now_str()
            
            return self.market_repo.upsert(
                self.TYPE_MARKET_SENTIMENT,
                sentiment_data,
                date.today(),
            )
            
        except Exception as e:
            logger.error(f"Failed to process market sentiment: {e}")
            return False
    
    async def refresh_index_overview(self) -> bool:
        """刷新大盘概况数据
        
        Returns:
            是否成功
        """
        try:
            ak = self.collector._get_ak()
            
            index_data = {
                "indices": [],
                "updated_at": now_str(),
            }
            
            try:
                # 获取主要指数数据
                df = ak.stock_zh_index_spot_em()
                if df is not None and not df.empty:
                    # 筛选主要指数
                    main_indices = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300", "中证500"]
                    
                    for idx_name in main_indices:
                        row = df[df["名称"] == idx_name]
                        if not row.empty:
                            row = row.iloc[0]
                            index_data["indices"].append({
                                "name": idx_name,
                                "code": row.get("代码", ""),
                                "current": float(row.get("最新价", 0) or 0),
                                "change": float(row.get("涨跌额", 0) or 0),
                                "change_pct": float(row.get("涨跌幅", 0) or 0),
                                "volume": float(row.get("成交量", 0) or 0),
                                "amount": float(row.get("成交额", 0) or 0),
                            })
                            
            except Exception as e:
                logger.warning(f"Failed to get index data: {e}")
            
            return self.market_repo.upsert(
                self.TYPE_INDEX_OVERVIEW,
                index_data,
                date.today(),
            )
            
        except Exception as e:
            logger.error(f"Failed to refresh index overview: {e}")
            return False
    
    async def refresh_hot_stocks(self, limit: Optional[int] = 500) -> bool:
        """刷新热门股票数据（单独调用时）

        Args:
            limit: 热门股票数量，None表示不限制，默认500只

        Returns:
            是否成功
        """
        try:
            ak = self.collector._get_ak()
            df = ak.stock_zh_a_spot_em()
            return await self._refresh_hot_stocks_with_data(df, limit)
        except Exception as e:
            logger.error(f"Failed to refresh hot stocks: {e}")
            return False
    
    async def _refresh_hot_stocks_with_data(self, df, limit: Optional[int] = 500) -> bool:
        """使用已获取的数据刷新热门股票

        Args:
            df: A股实时行情 DataFrame
            limit: 热门股票数量，None表示不限制

        Returns:
            是否成功
        """
        try:
            hot_stocks_data = {
                "stocks": [],
                "updated_at": now_str(),
            }

            if df is not None and not df.empty:
                # 按成交额排序
                df = df.sort_values("成交额", ascending=False)
                if limit is not None:
                    df = df.head(limit)
                
                today = today_str()
                quotes_to_save = []

                for _, row in df.iterrows():
                    stock_code = row.get("代码", "")

                    # 处理 NaN 值
                    def safe_float(val, default=0.0):
                        try:
                            result = float(val or 0)
                            return default if (result != result) else result  # NaN check
                        except (ValueError, TypeError):
                            return default

                    def safe_int(val, default=0):
                        try:
                            result = float(val or 0)
                            return default if (result != result) else int(result)  # NaN check
                        except (ValueError, TypeError):
                            return default

                    stock_info = {
                        "code": stock_code,
                        "name": row.get("名称", ""),
                        "current_price": safe_float(row.get("最新价")),
                        "change_pct": safe_float(row.get("涨跌幅")),
                        "volume": safe_int(row.get("成交量")),
                        "amount": safe_float(row.get("成交额")),
                        "turnover_rate": safe_float(row.get("换手率")),
                    }
                    hot_stocks_data["stocks"].append(stock_info)

                    # 构建行情数据，委托给 QuoteService 存储
                    from app.models.entities import StockQuote
                    quote = StockQuote(
                        stock_code=stock_code,
                        trade_date=today,
                        open_price=Decimal(str(safe_float(row.get("今开")))),
                        high_price=Decimal(str(safe_float(row.get("最高")))),
                        low_price=Decimal(str(safe_float(row.get("最低")))),
                        close_price=Decimal(str(safe_float(row.get("最新价")))),
                        prev_close=Decimal(str(safe_float(row.get("昨收")))),
                        volume=safe_int(row.get("成交量")),
                        amount=Decimal(str(safe_float(row.get("成交额")))),
                        stock_name=str(row.get("名称", "")) or None,
                    )
                    quotes_to_save.append(quote)
                
                # 委托 QuoteService 存储行情数据
                if self.quote_service and quotes_to_save:
                    success_count, fail_count = self.quote_service.upsert_quotes(quotes_to_save)
                    logger.info(f"委托 QuoteService 存储热门股票行情: 成功 {success_count}, 失败 {fail_count}")
                elif quotes_to_save:
                    # 如果没有注入 QuoteService，使用本地仓库（向后兼容）
                    from app.data.repositories import StockQuoteRepository
                    quote_repo = StockQuoteRepository(self.db)
                    for quote in quotes_to_save:
                        quote_repo.upsert(quote)
                    logger.info(f"本地存储热门股票行情: {len(quotes_to_save)} 条")
            
            return self.market_repo.upsert(
                self.TYPE_HOT_STOCKS,
                hot_stocks_data,
                date.today(),
            )
            
        except Exception as e:
            logger.error(f"Failed to process hot stocks: {e}")
            return False
    
    def get_all_market_data(self) -> Dict[str, Any]:
        """获取所有市场数据（从数据库）
        
        Returns:
            包含所有市场数据的字典
        """
        return self.market_repo.get_all_latest()
    
    def get_market_sentiment(self) -> Optional[Dict]:
        """获取市场情绪数据
        
        Returns:
            市场情绪数据
        """
        return self.market_repo.get_latest(self.TYPE_MARKET_SENTIMENT)
    
    def get_index_overview(self) -> Optional[Dict]:
        """获取大盘概况数据
        
        Returns:
            大盘概况数据
        """
        return self.market_repo.get_latest(self.TYPE_INDEX_OVERVIEW)
    
    def get_hot_stocks(self) -> Optional[Dict]:
        """获取热门股票数据
        
        Returns:
            热门股票数据
        """
        return self.market_repo.get_latest(self.TYPE_HOT_STOCKS)
    
    def get_market_data_for_prompt(self) -> Dict[str, Any]:
        """获取用于提示词的市场数据
        
        Returns:
            格式化的市场数据，可直接用于提示词
        """
        all_data = self.get_all_market_data()
        
        result = {}
        
        # 市场情绪
        sentiment = all_data.get(self.TYPE_MARKET_SENTIMENT)
        if sentiment:
            result["market_sentiment"] = sentiment.get("data", {})
        
        # 大盘概况
        index_overview = all_data.get(self.TYPE_INDEX_OVERVIEW)
        if index_overview:
            result["index_overview"] = index_overview.get("data", {})
        
        # 热门股票
        hot_stocks = all_data.get(self.TYPE_HOT_STOCKS)
        if hot_stocks:
            result["hot_stocks"] = hot_stocks.get("data", {}).get("stocks", [])
        
        return result
