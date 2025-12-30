"""股票数据服务

提供股票基本信息、实时行情、K线数据、资金流向、公司信息、资讯、财务数据等的获取功能。
封装AkShare接口，提供统一的错误处理和重试逻辑。
"""

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from sqlalchemy.orm import Session

from app.core.exceptions import StockDataError, StockNotFoundError
from app.core.timezone import today_str

# 禁用 AKShare 的 tqdm 进度条
os.environ["AKSHARE_TQDM"] = "0"

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============ 辅助函数 ============

def safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数，处理NaN和None值
    
    Args:
        value: 要转换的值
        default: 默认值
        
    Returns:
        转换后的浮点数，如果转换失败或为NaN则返回默认值
    """
    if value is None:
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """安全转换为整数，处理NaN和None值
    
    Args:
        value: 要转换的值
        default: 默认值
        
    Returns:
        转换后的整数，如果转换失败或为NaN则返回默认值
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        return int(float_val)
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """安全转换为字符串，处理None值
    
    Args:
        value: 要转换的值
        default: 默认值
        
    Returns:
        转换后的字符串，如果为None则返回默认值
    """
    if value is None:
        return default
    return str(value)


# ============ 数据模型 ============

@dataclass
class StockBasicInfo:
    """股票基本信息"""
    code: str           # 股票代码
    name: str           # 股票名称
    market: str         # 市场（SH/SZ）
    industry: str       # 所属行业
    list_date: str      # 上市日期

@dataclass
class StockRealtimeQuote:
    """股票实时行情"""
    price: float          # 当前价格
    change: float         # 涨跌额
    change_pct: float     # 涨跌幅
    open: float           # 今开
    high: float           # 最高
    low: float            # 最低
    prev_close: float     # 昨收
    volume: int           # 成交量
    amount: float         # 成交额
    turnover_rate: float  # 换手率
    pe: float             # 市盈率
    pb: float             # 市净率
    market_cap: float     # 总市值
    updated_at: str       # 更新时间


@dataclass
class KLineData:
    """K线数据"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float


@dataclass
class MinuteData:
    """分时数据（分钟级别）"""
    time: str           # 时间 (YYYY-MM-DD HH:MM:SS)
    open: float         # 开盘价
    high: float         # 最高价
    low: float          # 最低价
    close: float        # 收盘价
    volume: int         # 成交量
    amount: float       # 成交额
    avg_price: float    # 均价


@dataclass
class CapitalFlowData:
    """资金流向数据"""
    date: str               # 日期
    main_inflow: float      # 主力流入
    main_outflow: float     # 主力流出
    main_net: float         # 主力净流入
    retail_inflow: float    # 散户流入
    retail_outflow: float   # 散户流出
    retail_net: float       # 散户净流入
    total_inflow: float     # 总流入
    total_outflow: float    # 总流出
    total_net: float        # 净流入


@dataclass
class CapitalDistribution:
    """资金分布数据"""
    super_large_inflow: float   # 超大单流入
    super_large_outflow: float  # 超大单流出
    super_large_net: float      # 超大单净流入
    large_inflow: float         # 大单流入
    large_outflow: float        # 大单流出
    large_net: float            # 大单净流入
    medium_inflow: float        # 中单流入
    medium_outflow: float       # 中单流出
    medium_net: float           # 中单净流入
    small_inflow: float         # 小单流入
    small_outflow: float        # 小单流出
    small_net: float            # 小单净流入


@dataclass
class CompanyProfile:
    """公司简介"""
    name: str                   # 公司名称
    english_name: str           # 英文名称
    industry: str               # 所属行业
    list_date: str              # 上市日期
    total_shares: float         # 总股本
    circulating_shares: float   # 流通股本
    description: str            # 公司简介
    main_business: str          # 主营业务
    registered_capital: float   # 注册资本
    employees: int              # 员工人数
    province: str               # 所在省份
    city: str                   # 所在城市
    website: str                # 公司网站


@dataclass
class Shareholder:
    """股东信息"""
    name: str           # 股东名称
    shares: float       # 持股数量
    percentage: float   # 持股比例
    nature: str         # 股东性质


@dataclass
class Executive:
    """高管信息"""
    name: str           # 姓名
    position: str       # 职位
    salary: float       # 薪酬
    shares: float       # 持股数量


@dataclass
class StockNews:
    """股票新闻"""
    id: str                 # 新闻ID
    title: str              # 新闻标题
    source: str             # 来源
    publish_time: str       # 发布时间
    url: str                # 链接
    sentiment: str          # 情感（positive/negative/neutral）
    summary: str            # 摘要


@dataclass
class AnalystRating:
    """机构评级"""
    institution: str        # 机构名称
    analyst: str            # 分析师
    rating: str             # 评级（买入/增持/中性/减持/卖出）
    target_price: float     # 目标价
    date: str               # 日期


@dataclass
class FinancialMetrics:
    """财务指标"""
    report_date: str        # 报告期
    revenue: float          # 营业收入
    revenue_yoy: float      # 营收同比
    net_profit: float       # 净利润
    net_profit_yoy: float   # 净利润同比
    gross_margin: float     # 毛利率
    net_margin: float       # 净利率
    roe: float              # 净资产收益率
    eps: float              # 每股收益
    bps: float              # 每股净资产


@dataclass
class BalanceSheet:
    """资产负债表"""
    report_date: str            # 报告期
    total_assets: float         # 总资产
    total_liabilities: float    # 总负债
    total_equity: float         # 股东权益
    current_assets: float       # 流动资产
    current_liabilities: float  # 流动负债
    cash_and_equivalents: float # 货币资金


@dataclass
class CashFlow:
    """现金流量表"""
    report_date: str                # 报告期
    operating_cash_flow: float      # 经营活动现金流
    investing_cash_flow: float      # 投资活动现金流
    financing_cash_flow: float      # 筹资活动现金流
    net_cash_flow: float            # 现金净流量


# ============ 服务类 ============

class StockDataService:
    """股票数据服务 - 封装AkShare接口
    
    提供股票基本信息、实时行情、K线数据等的获取功能。
    包含通用的错误处理和重试逻辑。
    """
    
    def __init__(
        self,
        db: Session = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """初始化股票数据服务
        
        Args:
            db: 数据库会话（可选，用于缓存）
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）
        """
        self.db = db
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._ak = None
    
    def _get_ak(self):
        """延迟加载AkShare
        
        Returns:
            AkShare模块实例
            
        Raises:
            StockDataError: AkShare未安装
        """
        if self._ak is None:
            try:
                import akshare as ak
                self._ak = ak
            except ImportError:
                logger.error("AkShare not installed")
                raise StockDataError(
                    message="AkShare 未安装，请运行: pip install akshare",
                    source="AkShare",
                )
        return self._ak

    def _get_market_code(self, stock_code: str) -> str:
        """根据股票代码获取市场代码

        Args:
            stock_code: 6位股票代码

        Returns:
            市场代码: 'sh' 或 'sz'
        """
        if stock_code.startswith(('6', '5')):
            return 'sh'
        else:
            return 'sz'

    async def _run_sync(self, func: Callable[..., T], *args, **kwargs) -> T:
        """在线程池中运行同步函数
        
        Args:
            func: 同步函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数返回值
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    
    async def _fetch_with_retry(
        self,
        func: Callable[..., T],
        *args,
        stock_code: Optional[str] = None,
        **kwargs,
    ) -> T:
        """带重试的数据获取
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            stock_code: 股票代码（用于错误信息，不传递给func）
            **kwargs: 关键字参数
            
        Returns:
            函数返回值
            
        Raises:
            StockDataError: 所有重试都失败
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                # 注意：stock_code 只用于错误信息，不传递给 func
                return await self._run_sync(func, *args)
            except StockDataError:
                # 自定义异常直接抛出，不重试
                raise
            except Exception as e:
                last_error = e
                logger.warning(
                    f"AkShare attempt {attempt + 1}/{self.max_retries} failed: {e}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
        
        logger.error(f"All {self.max_retries} attempts failed: {last_error}")
        raise StockDataError(
            message=f"数据获取失败，请稍后重试: {last_error}",
            stock_code=stock_code,
            source="AkShare",
        )
    
    # ============ 股票基本信息 ============
    
    async def get_stock_info(self, stock_code: str) -> StockBasicInfo:
        """获取股票基本信息
        
        使用 stock_individual_info_em 接口获取股票基本信息。
        
        Args:
            stock_code: 股票代码（6位数字）
            
        Returns:
            StockBasicInfo 股票基本信息
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_stock_info_sync,
            stock_code,
            stock_code=stock_code,
        )
    
    def _get_stock_info_sync(self, stock_code: str) -> StockBasicInfo:
        """同步获取股票基本信息"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_individual_info_em 获取个股信息
            df = ak.stock_individual_info_em(symbol=stock_code)
            
            if df is None or df.empty:
                raise StockNotFoundError(stock_code)
            
            # 将DataFrame转换为字典，方便查找
            info_dict = {}
            for _, row in df.iterrows():
                item = safe_str(row.get("item"))
                value = safe_str(row.get("value"))
                info_dict[item] = value
            
            # 确定市场
            market = "SH" if stock_code.startswith("6") else "SZ"
            
            return StockBasicInfo(
                code=stock_code,
                name=safe_str(info_dict.get("股票简称")),
                market=market,
                industry=safe_str(info_dict.get("行业")),
                list_date=safe_str(info_dict.get("上市时间")),
            )
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get stock info for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取股票信息失败: {e}",
                stock_code=stock_code,
            )
    
    # ============ 实时行情 ============
    
    async def get_realtime_quote(self, stock_code: str) -> StockRealtimeQuote:
        """获取实时行情
        
        使用 stock_zh_a_spot_em 接口获取A股实时行情。
        
        Args:
            stock_code: 股票代码（6位数字）
            
        Returns:
            StockRealtimeQuote 实时行情数据
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_realtime_quote_sync,
            stock_code,
            stock_code=stock_code,
        )
    
    def _get_realtime_quote_sync(self, stock_code: str) -> StockRealtimeQuote:
        """同步获取实时行情"""
        ak = self._get_ak()
        
        try:
            # 获取A股实时行情
            df = ak.stock_zh_a_spot_em()
            
            if df is None or df.empty:
                raise StockDataError(
                    message="无法获取A股行情数据",
                    stock_code=stock_code,
                )
            
            # 查找指定股票
            row = df[df["代码"] == stock_code]
            if row.empty:
                raise StockNotFoundError(stock_code)
            
            row = row.iloc[0]
            
            return StockRealtimeQuote(
                price=safe_float(row.get("最新价")),
                change=safe_float(row.get("涨跌额")),
                change_pct=safe_float(row.get("涨跌幅")),
                open=safe_float(row.get("今开")),
                high=safe_float(row.get("最高")),
                low=safe_float(row.get("最低")),
                prev_close=safe_float(row.get("昨收")),
                volume=safe_int(row.get("成交量")),
                amount=safe_float(row.get("成交额")),
                turnover_rate=safe_float(row.get("换手率")),
                pe=safe_float(row.get("市盈率-动态")),
                pb=safe_float(row.get("市净率")),
                market_cap=safe_float(row.get("总市值")),
                updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get realtime quote for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取实时行情失败: {e}",
                stock_code=stock_code,
            )
    
    # ============ K线数据 ============
    
    async def get_kline_data(
        self,
        stock_code: str,
        period: str = "daily",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[KLineData]:
        """获取K线数据
        
        使用 stock_zh_a_hist 接口获取K线历史数据。
        
        Args:
            stock_code: 股票代码（6位数字）
            period: 周期类型 (daily/weekly/monthly)
            start_date: 开始日期 (YYYY-MM-DD)，可选
            end_date: 结束日期 (YYYY-MM-DD)，可选
            limit: 返回数据条数限制
            
        Returns:
            List[KLineData] K线数据列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_kline_data_sync,
            stock_code,
            period,
            start_date,
            end_date,
            limit,
            stock_code=stock_code,
        )
    
    def _get_kline_data_sync(
        self,
        stock_code: str,
        period: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int,
    ) -> List[KLineData]:
        """同步获取K线数据"""
        ak = self._get_ak()

        try:
            # 转换周期参数
            period_map = {
                "daily": "daily",
                "weekly": "weekly",
                "monthly": "monthly",
            }
            ak_period = period_map.get(period, "daily")

            # 格式化日期（去掉横线）
            start = start_date.replace("-", "") if start_date else None
            end = end_date.replace("-", "") if end_date else None

            logger.debug(f"Fetching kline: stock={stock_code}, period={ak_period}, start={start}, end={end}, limit={limit}")

            # 获取K线数据
            logger.debug(f"Calling ak.stock_zh_a_hist with symbol={stock_code}, period={ak_period}, start_date={start}, end_date={end}")
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period=ak_period,
                start_date=start if start else "19700101",
                end_date=end if end else "20500101",
                adjust="",  # 不复权
            )

            logger.debug(f"AkShare returned: type={type(df)}, rows={len(df) if df is not None and not df.empty else 0}, is_none={df is None}, is_empty={df.empty if df is not None else 'N/A'}")

            if df is None or df.empty:
                logger.warning(f"No kline data for {stock_code}")
                return []

            logger.debug(f"DataFrame columns: {list(df.columns)}")

            # 限制返回条数
            if limit and len(df) > limit:
                df = df.tail(limit)

            klines = []
            for idx, row in df.iterrows():
                try:
                    kline = KLineData(
                        date=safe_str(row.get("日期")),
                        open=safe_float(row.get("开盘")),
                        high=safe_float(row.get("最高")),
                        low=safe_float(row.get("最低")),
                        close=safe_float(row.get("收盘")),
                        volume=safe_int(row.get("成交量")),
                        amount=safe_float(row.get("成交额")),
                    )
                    klines.append(kline)
                except Exception as e:
                    logger.error(f"Error processing kline row {idx}: {e}")
                    continue

            logger.debug(f"Processed {len(klines)} klines for {stock_code}")
            return klines
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get kline data for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取K线数据失败: {e}",
                stock_code=stock_code,
            )

    # ============ 分时数据 ============

    async def get_minute_data(
        self,
        stock_code: str,
        period: str = "1",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[MinuteData]:
        """获取分时数据

        使用 stock_zh_a_hist_min_em 接口获取分钟级别的历史数据。

        Args:
            stock_code: 股票代码（6位数字）
            period: 周期类型 ('1', '5', '15', '30', '60')，默认1分钟
            start_date: 开始日期时间 (YYYY-MM-DD HH:MM:SS)，可选
            end_date: 结束日期时间 (YYYY-MM-DD HH:MM:SS)，可选

        Returns:
            List[MinuteData] 分时数据列表

        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_minute_data_sync,
            stock_code,
            period,
            start_date,
            end_date,
            stock_code=stock_code,
        )

    def _get_minute_data_sync(
        self,
        stock_code: str,
        period: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> List[MinuteData]:
        """同步获取分时数据"""
        ak = self._get_ak()

        try:
            # 验证周期参数
            if period not in ['1', '5', '15', '30', '60']:
                period = '1'

            # 设置默认时间范围（最近5个交易日）
            if not start_date:
                start_date = "1979-09-01 09:32:00"
            if not end_date:
                end_date = "2222-01-01 09:32:00"

            logger.debug(f"Fetching minute data: stock={stock_code}, period={period}, start={start_date}, end={end_date}")

            # 获取分时数据
            df = ak.stock_zh_a_hist_min_em(
                symbol=stock_code,
                start_date=start_date,
                end_date=end_date,
                period=period,
                adjust="",  # 不复权
            )

            logger.debug(f"AkShare returned: rows={len(df) if df is not None and not df.empty else 0}")

            if df is None or df.empty:
                logger.warning(f"No minute data for {stock_code}")
                return []

            logger.debug(f"DataFrame columns: {list(df.columns)}")

            minutes = []
            for idx, row in df.iterrows():
                try:
                    minute = MinuteData(
                        time=safe_str(row.get("时间")),
                        open=safe_float(row.get("开盘")),
                        high=safe_float(row.get("最高")),
                        low=safe_float(row.get("最低")),
                        close=safe_float(row.get("收盘")),
                        volume=safe_int(row.get("成交量")),
                        amount=safe_float(row.get("成交额")),
                        avg_price=safe_float(row.get("均价", row.get("收盘"))),  # 如果没有均价，使用收盘价
                    )
                    minutes.append(minute)
                except Exception as e:
                    logger.warning(f"Failed to parse minute data row {idx}: {e}")
                    continue

            logger.info(f"Successfully parsed {len(minutes)} minute data points for {stock_code}")
            return minutes

        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get minute data for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取分时数据失败: {e}",
                stock_code=stock_code,
            )

    # ============ 资金流向 ============
    
    async def get_capital_flow(
        self,
        stock_code: str,
        days: int = 5,
    ) -> List[CapitalFlowData]:
        """获取资金流向数据
        
        使用 stock_individual_fund_flow 接口获取个股资金流向。
        
        Args:
            stock_code: 股票代码（6位数字）
            days: 获取天数，默认5天
            
        Returns:
            List[CapitalFlowData] 资金流向数据列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_capital_flow_sync,
            stock_code,
            days,
            stock_code=stock_code,
        )
    
    def _get_capital_flow_sync(
        self,
        stock_code: str,
        days: int,
    ) -> List[CapitalFlowData]:
        """同步获取资金流向数据"""
        ak = self._get_ak()
        
        try:
            # 确定市场
            market = "sh" if stock_code.startswith("6") else "sz"
            
            # 获取个股资金流向
            df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
            
            if df is None or df.empty:
                return []
            
            # 限制返回天数
            if days and len(df) > days:
                df = df.tail(days)
            
            flows = []
            for _, row in df.iterrows():
                # 解析资金流向数据
                # AkShare返回的列名可能包含：日期、主力净流入-净额、小单净流入-净额等
                main_inflow = safe_float(row.get("主力流入-净额"))
                main_outflow = safe_float(row.get("主力流出-净额")) if "主力流出-净额" in row.index else 0
                retail_inflow = safe_float(row.get("小单流入-净额")) if "小单流入-净额" in row.index else 0
                retail_outflow = safe_float(row.get("小单流出-净额")) if "小单流出-净额" in row.index else 0
                
                flow = CapitalFlowData(
                    date=safe_str(row.get("日期")),
                    main_inflow=main_inflow,
                    main_outflow=main_outflow,
                    main_net=safe_float(row.get("主力净流入-净额")),
                    retail_inflow=retail_inflow,
                    retail_outflow=retail_outflow,
                    retail_net=safe_float(row.get("小单净流入-净额")),
                    total_inflow=main_inflow + retail_inflow,
                    total_outflow=main_outflow + retail_outflow,
                    total_net=safe_float(row.get("主力净流入-净额")) + safe_float(row.get("小单净流入-净额")),
                )
                flows.append(flow)
            
            return flows
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get capital flow for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取资金流向失败: {e}",
                stock_code=stock_code,
            )
    
    async def get_capital_distribution(
        self,
        stock_code: str,
    ) -> CapitalDistribution:
        """获取资金分布数据
        
        使用 stock_individual_fund_flow 接口获取个股资金分布。
        
        Args:
            stock_code: 股票代码（6位数字）
            
        Returns:
            CapitalDistribution 资金分布数据
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_capital_distribution_sync,
            stock_code,
            stock_code=stock_code,
        )
    
    def _get_capital_distribution_sync(
        self,
        stock_code: str,
    ) -> CapitalDistribution:
        """同步获取资金分布数据"""
        ak = self._get_ak()
        
        try:
            # 确定市场
            market = "sh" if stock_code.startswith("6") else "sz"
            
            # 获取个股资金流向（最新一天的数据）
            df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
            
            if df is None or df.empty:
                # 返回空的资金分布
                return CapitalDistribution(
                    super_large_inflow=0, super_large_outflow=0, super_large_net=0,
                    large_inflow=0, large_outflow=0, large_net=0,
                    medium_inflow=0, medium_outflow=0, medium_net=0,
                    small_inflow=0, small_outflow=0, small_net=0,
                )
            
            # 取最新一天的数据
            row = df.iloc[-1]
            
            # 解析资金分布数据
            # AkShare返回的列名：超大单净流入-净额、大单净流入-净额、中单净流入-净额、小单净流入-净额
            return CapitalDistribution(
                super_large_inflow=safe_float(row.get("超大单流入-净额")) if "超大单流入-净额" in row.index else 0,
                super_large_outflow=safe_float(row.get("超大单流出-净额")) if "超大单流出-净额" in row.index else 0,
                super_large_net=safe_float(row.get("超大单净流入-净额")),
                large_inflow=safe_float(row.get("大单流入-净额")) if "大单流入-净额" in row.index else 0,
                large_outflow=safe_float(row.get("大单流出-净额")) if "大单流出-净额" in row.index else 0,
                large_net=safe_float(row.get("大单净流入-净额")),
                medium_inflow=safe_float(row.get("中单流入-净额")) if "中单流入-净额" in row.index else 0,
                medium_outflow=safe_float(row.get("中单流出-净额")) if "中单流出-净额" in row.index else 0,
                medium_net=safe_float(row.get("中单净流入-净额")),
                small_inflow=safe_float(row.get("小单流入-净额")) if "小单流入-净额" in row.index else 0,
                small_outflow=safe_float(row.get("小单流出-净额")) if "小单流出-净额" in row.index else 0,
                small_net=safe_float(row.get("小单净流入-净额")),
            )
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get capital distribution for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取资金分布失败: {e}",
                stock_code=stock_code,
            )
    
    # ============ 公司信息 ============
    
    async def get_company_profile(self, stock_code: str) -> CompanyProfile:
        """获取公司简介
        
        使用 stock_individual_info_em 接口获取公司详细信息。
        
        Args:
            stock_code: 股票代码（6位数字）
            
        Returns:
            CompanyProfile 公司简介
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_company_profile_sync,
            stock_code,
            stock_code=stock_code,
        )
    
    def _get_company_profile_sync(self, stock_code: str) -> CompanyProfile:
        """同步获取公司简介"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_individual_info_em 获取个股信息
            df = ak.stock_individual_info_em(symbol=stock_code)
            
            if df is None or df.empty:
                raise StockNotFoundError(stock_code)
            
            # 将DataFrame转换为字典，方便查找
            info_dict = {}
            for _, row in df.iterrows():
                item = safe_str(row.get("item"))
                value = safe_str(row.get("value"))
                info_dict[item] = value
            
            return CompanyProfile(
                name=safe_str(info_dict.get("股票简称")),
                english_name=safe_str(info_dict.get("英文名称")),
                industry=safe_str(info_dict.get("行业")),
                list_date=safe_str(info_dict.get("上市时间")),
                total_shares=safe_float(info_dict.get("总股本")),
                circulating_shares=safe_float(info_dict.get("流通股")),
                description=safe_str(info_dict.get("经营范围")),
                main_business=safe_str(info_dict.get("主营业务")),
                registered_capital=safe_float(info_dict.get("注册资本")),
                employees=safe_int(info_dict.get("员工人数")),
                province=safe_str(info_dict.get("省份")),
                city=safe_str(info_dict.get("城市")),
                website=safe_str(info_dict.get("公司网址")),
            )
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get company profile for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取公司简介失败: {e}",
                stock_code=stock_code,
            )
    
    async def get_shareholders(self, stock_code: str) -> List[Shareholder]:
        """获取股东信息
        
        使用 stock_gdfx_free_holding_detail_em 接口获取十大流通股东。
        
        Args:
            stock_code: 股票代码（6位数字）
            
        Returns:
            List[Shareholder] 股东信息列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_shareholders_sync,
            stock_code,
            stock_code=stock_code,
        )
    
    def _get_shareholders_sync(self, stock_code: str) -> List[Shareholder]:
        """同步获取股东信息"""
        ak = self._get_ak()

        try:
            # 使用 stock_gdfx_free_top_10_em 获取十大流通股东
            # 需要添加市场前缀（sh/sz）
            market_code = self._get_market_code(stock_code)
            symbol_with_market = f"{market_code}{stock_code}"

            # 获取最新的报告期数据
            from datetime import datetime
            current_date = datetime.now()
            # 尝试最近几个季度的数据
            quarters = [
                f"{current_date.year}0930",  # Q3
                f"{current_date.year}0630",  # Q2
                f"{current_date.year}0331",  # Q1
                f"{current_date.year - 1}1231",  # 上年Q4
            ]

            df = None
            for quarter in quarters:
                try:
                    df = ak.stock_gdfx_free_top_10_em(symbol=symbol_with_market, date=quarter)
                    if df is not None and not df.empty:
                        break
                except:
                    continue

            if df is None or df.empty:
                logger.warning(f"No shareholder data for {stock_code}")
                return []

            shareholders = []
            for _, row in df.iterrows():
                shareholder = Shareholder(
                    name=safe_str(row.get("股东名称")),
                    shares=safe_float(row.get("持股数量")),
                    percentage=safe_float(row.get("持股比例")),
                    nature=safe_str(row.get("股东性质")),
                )
                shareholders.append(shareholder)

            # 限制返回前10个股东
            return shareholders[:10]
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get shareholders for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取股东信息失败: {e}",
                stock_code=stock_code,
            )
    
    async def get_executives(self, stock_code: str) -> List[Executive]:
        """获取高管信息
        
        使用 stock_ggcg_em 接口获取高管持股变动信息。
        
        Args:
            stock_code: 股票代码（6位数字）
            
        Returns:
            List[Executive] 高管信息列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_executives_sync,
            stock_code,
            stock_code=stock_code,
        )
    
    def _get_executives_sync(self, stock_code: str) -> List[Executive]:
        """同步获取高管信息"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_ggcg_em 获取高管持股变动
            # 注意：这个接口返回的是高管持股变动记录，不是完整的高管列表
            df = ak.stock_ggcg_em(symbol=stock_code)
            
            if df is None or df.empty:
                return []
            
            # 按高管姓名去重，保留最新记录
            executives_dict = {}
            for _, row in df.iterrows():
                name = safe_str(row.get("变动人"))
                if name and name not in executives_dict:
                    executives_dict[name] = Executive(
                        name=name,
                        position=safe_str(row.get("变动人与董监高的关系")),
                        salary=0,  # 该接口不提供薪酬信息
                        shares=safe_float(row.get("变动后持股数")),
                    )
            
            return list(executives_dict.values())[:20]  # 限制返回前20个
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get executives for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取高管信息失败: {e}",
                stock_code=stock_code,
            )

    # ============ 资讯接口 ============
    
    async def get_stock_news(
        self,
        stock_code: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[StockNews]:
        """获取股票新闻
        
        使用 stock_news_em 接口获取股票相关新闻。
        
        Args:
            stock_code: 股票代码（6位数字）
            page: 页码，默认1
            page_size: 每页条数，默认20
            
        Returns:
            List[StockNews] 新闻列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_stock_news_sync,
            stock_code,
            page,
            page_size,
            stock_code=stock_code,
        )
    
    def _get_stock_news_sync(
        self,
        stock_code: str,
        page: int,
        page_size: int,
    ) -> List[StockNews]:
        """同步获取股票新闻"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_news_em 获取股票新闻
            df = ak.stock_news_em(symbol=stock_code)
            
            if df is None or df.empty:
                return []
            
            # 分页处理
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            df = df.iloc[start_idx:end_idx]
            
            news_list = []
            for idx, row in df.iterrows():
                # 简单的情感分析：基于标题关键词
                title = str(row.get("新闻标题", ""))
                sentiment = self._analyze_sentiment(title)
                
                news = StockNews(
                    id=str(idx),
                    title=title,
                    source=str(row.get("新闻来源", "") or ""),
                    publish_time=str(row.get("发布时间", "") or ""),
                    url=str(row.get("新闻链接", "") or ""),
                    sentiment=sentiment,
                    summary=str(row.get("新闻内容", "") or "")[:200],  # 截取前200字作为摘要
                )
                news_list.append(news)
            
            return news_list
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get stock news for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取股票新闻失败: {e}",
                stock_code=stock_code,
            )
    
    def _analyze_sentiment(self, text: str) -> str:
        """简单的情感分析
        
        基于关键词判断新闻情感倾向。
        
        Args:
            text: 文本内容
            
        Returns:
            情感标签: positive/negative/neutral
        """
        positive_keywords = [
            "涨", "上涨", "大涨", "涨停", "利好", "增长", "突破", "新高",
            "盈利", "增持", "买入", "推荐", "看好", "强势", "反弹", "回升",
        ]
        negative_keywords = [
            "跌", "下跌", "大跌", "跌停", "利空", "下滑", "亏损", "减持",
            "卖出", "风险", "警示", "暴跌", "破位", "新低", "回调", "下挫",
        ]
        
        positive_count = sum(1 for kw in positive_keywords if kw in text)
        negative_count = sum(1 for kw in negative_keywords if kw in text)
        
        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        else:
            return "neutral"
    
    async def get_analyst_ratings(self, stock_code: str) -> List[AnalystRating]:
        """获取机构评级
        
        使用 stock_comment_em 接口获取机构评级信息。
        
        Args:
            stock_code: 股票代码（6位数字）
            
        Returns:
            List[AnalystRating] 机构评级列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_analyst_ratings_sync,
            stock_code,
            stock_code=stock_code,
        )
    
    def _get_analyst_ratings_sync(self, stock_code: str) -> List[AnalystRating]:
        """同步获取机构评级"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_comment_em 获取机构评级
            # 注意：这个接口返回的是所有股票的评级汇总，需要筛选
            df = ak.stock_comment_em()
            
            if df is None or df.empty:
                return []
            
            # 筛选指定股票
            row = df[df["代码"] == stock_code]
            if row.empty:
                return []
            
            row = row.iloc[0]
            
            # 构建评级信息
            # stock_comment_em 返回的是综合评级，不是单个机构的评级
            # 我们将其转换为单条评级记录
            rating_map = {
                "买入": "买入",
                "增持": "增持",
                "中性": "中性",
                "减持": "减持",
                "卖出": "卖出",
            }
            
            # 获取综合评级
            comprehensive_rating = str(row.get("综合评级", "中性") or "中性")
            
            ratings = [
                AnalystRating(
                    institution="综合评级",
                    analyst="",
                    rating=comprehensive_rating,
                    target_price=0,  # 该接口不提供目标价
                    date=str(row.get("交易日", "") or ""),
                )
            ]
            
            return ratings
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get analyst ratings for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取机构评级失败: {e}",
                stock_code=stock_code,
            )
    
    # ============ 财务数据接口 ============
    
    async def get_financial_metrics(
        self,
        stock_code: str,
        report_type: str = "quarterly",
        periods: int = 4,
    ) -> List[FinancialMetrics]:
        """获取财务指标
        
        使用 stock_financial_analysis_indicator 接口获取财务分析指标。
        
        Args:
            stock_code: 股票代码（6位数字）
            report_type: 报告类型 (quarterly/annual)
            periods: 获取期数，默认4期
            
        Returns:
            List[FinancialMetrics] 财务指标列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_financial_metrics_sync,
            stock_code,
            report_type,
            periods,
            stock_code=stock_code,
        )
    
    def _get_financial_metrics_sync(
        self,
        stock_code: str,
        report_type: str,
        periods: int,
    ) -> List[FinancialMetrics]:
        """同步获取财务指标"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_financial_analysis_indicator 获取财务分析指标
            df = ak.stock_financial_analysis_indicator(symbol=stock_code)
            
            if df is None or df.empty:
                return []
            
            # 限制返回期数
            if periods and len(df) > periods:
                df = df.head(periods)
            
            metrics_list = []
            for _, row in df.iterrows():
                metrics = FinancialMetrics(
                    report_date=safe_str(row.get("日期")),
                    revenue=safe_float(row.get("营业总收入")),
                    revenue_yoy=safe_float(row.get("营业总收入同比增长率")),
                    net_profit=safe_float(row.get("净利润")),
                    net_profit_yoy=safe_float(row.get("净利润同比增长率")),
                    gross_margin=safe_float(row.get("销售毛利率")),
                    net_margin=safe_float(row.get("销售净利率")),
                    roe=safe_float(row.get("净资产收益率")),
                    eps=safe_float(row.get("基本每股收益")),
                    bps=safe_float(row.get("每股净资产")),
                )
                metrics_list.append(metrics)
            
            return metrics_list
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get financial metrics for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取财务指标失败: {e}",
                stock_code=stock_code,
            )
    
    async def get_balance_sheet(
        self,
        stock_code: str,
        periods: int = 4,
    ) -> List[BalanceSheet]:
        """获取资产负债表
        
        使用 stock_balance_sheet_by_report_em 接口获取资产负债表。
        
        Args:
            stock_code: 股票代码（6位数字）
            periods: 获取期数，默认4期
            
        Returns:
            List[BalanceSheet] 资产负债表列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_balance_sheet_sync,
            stock_code,
            periods,
            stock_code=stock_code,
        )
    
    def _get_balance_sheet_sync(
        self,
        stock_code: str,
        periods: int,
    ) -> List[BalanceSheet]:
        """同步获取资产负债表"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_balance_sheet_by_report_em 获取资产负债表
            df = ak.stock_balance_sheet_by_report_em(symbol=stock_code)
            
            if df is None or df.empty:
                return []
            
            # 限制返回期数
            if periods and len(df) > periods:
                df = df.head(periods)
            
            balance_sheets = []
            for _, row in df.iterrows():
                balance_sheet = BalanceSheet(
                    report_date=safe_str(row.get("REPORT_DATE") or row.get("报告期")),
                    total_assets=safe_float(row.get("TOTAL_ASSETS") or row.get("资产总计")),
                    total_liabilities=safe_float(row.get("TOTAL_LIABILITIES") or row.get("负债合计")),
                    total_equity=safe_float(row.get("TOTAL_EQUITY") or row.get("股东权益合计")),
                    current_assets=safe_float(row.get("TOTAL_CURRENT_ASSETS") or row.get("流动资产合计")),
                    current_liabilities=safe_float(row.get("TOTAL_CURRENT_LIAB") or row.get("流动负债合计")),
                    cash_and_equivalents=safe_float(row.get("MONETARYFUNDS") or row.get("货币资金")),
                )
                balance_sheets.append(balance_sheet)
            
            return balance_sheets
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get balance sheet for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取资产负债表失败: {e}",
                stock_code=stock_code,
            )
    
    async def get_cash_flow(
        self,
        stock_code: str,
        periods: int = 4,
    ) -> List[CashFlow]:
        """获取现金流量表
        
        使用 stock_cash_flow_sheet_by_report_em 接口获取现金流量表。
        
        Args:
            stock_code: 股票代码（6位数字）
            periods: 获取期数，默认4期
            
        Returns:
            List[CashFlow] 现金流量表列表
            
        Raises:
            StockNotFoundError: 股票不存在
            StockDataError: 数据获取失败
        """
        return await self._fetch_with_retry(
            self._get_cash_flow_sync,
            stock_code,
            periods,
            stock_code=stock_code,
        )
    
    def _get_cash_flow_sync(
        self,
        stock_code: str,
        periods: int,
    ) -> List[CashFlow]:
        """同步获取现金流量表"""
        ak = self._get_ak()
        
        try:
            # 使用 stock_cash_flow_sheet_by_report_em 获取现金流量表
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=stock_code)
            
            if df is None or df.empty:
                return []
            
            # 限制返回期数
            if periods and len(df) > periods:
                df = df.head(periods)
            
            cash_flows = []
            for _, row in df.iterrows():
                cash_flow = CashFlow(
                    report_date=safe_str(row.get("REPORT_DATE") or row.get("报告期")),
                    operating_cash_flow=safe_float(row.get("NETCASH_OPERATE") or row.get("经营活动产生的现金流量净额")),
                    investing_cash_flow=safe_float(row.get("NETCASH_INVEST") or row.get("投资活动产生的现金流量净额")),
                    financing_cash_flow=safe_float(row.get("NETCASH_FINANCE") or row.get("筹资活动产生的现金流量净额")),
                    net_cash_flow=safe_float(row.get("NETCASH_INCREASE") or row.get("现金及现金等价物净增加额")),
                )
                cash_flows.append(cash_flow)
            
            return cash_flows
            
        except StockDataError:
            raise
        except Exception as e:
            logger.error(f"Failed to get cash flow for {stock_code}: {e}")
            raise StockDataError(
                message=f"获取现金流量表失败: {e}",
                stock_code=stock_code,
            )
