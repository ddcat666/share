"""股票数据API路由

提供股票基本信息、实时行情、K线数据、资金流向、公司信息、资讯、财务数据等的查询接口。
集成Redis缓存，减少对AkShare API的调用频率。
"""

import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import StockDataError, StockNotFoundError
from app.core.cache import cache_service, CacheTTL
from app.data.stock_service import StockDataService
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ============ Pydantic响应模型 ============

class StockBasicInfoResponse(BaseModel):
    """股票基本信息响应"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    market: str = Field(..., description="市场（SH/SZ）")
    industry: str = Field(..., description="所属行业")
    list_date: str = Field(..., description="上市日期")


class StockRealtimeQuoteResponse(BaseModel):
    """股票实时行情响应"""
    price: float = Field(..., description="当前价格")
    change: float = Field(..., description="涨跌额")
    change_pct: float = Field(..., description="涨跌幅")
    open: float = Field(..., description="今开")
    high: float = Field(..., description="最高")
    low: float = Field(..., description="最低")
    prev_close: float = Field(..., description="昨收")
    volume: int = Field(..., description="成交量")
    amount: float = Field(..., description="成交额")
    turnover_rate: float = Field(..., description="换手率")
    pe: float = Field(..., description="市盈率")
    pb: float = Field(..., description="市净率")
    market_cap: float = Field(..., description="总市值")
    updated_at: str = Field(..., description="更新时间")


class KLineDataResponse(BaseModel):
    """K线数据响应"""
    date: str = Field(..., description="日期")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: int = Field(..., description="成交量")
    amount: float = Field(..., description="成交额")


class KLineListResponse(BaseModel):
    """K线数据列表响应"""
    stock_code: str = Field(..., description="股票代码")
    period: str = Field(..., description="周期类型")
    data: List[KLineDataResponse] = Field(..., description="K线数据列表")


class MinuteDataResponse(BaseModel):
    """分时数据响应"""
    time: str = Field(..., description="时间 (YYYY-MM-DD HH:MM:SS)")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: int = Field(..., description="成交量")
    amount: float = Field(..., description="成交额")
    avg_price: float = Field(..., description="均价")


class MinuteDataListResponse(BaseModel):
    """分时数据列表响应"""
    stock_code: str = Field(..., description="股票代码")
    period: str = Field(..., description="周期类型 (1/5/15/30/60分钟)")
    data: List[MinuteDataResponse] = Field(..., description="分时数据列表")


# ============ 资金流向响应模型 ============

class CapitalFlowDataResponse(BaseModel):
    """资金流向数据响应"""
    date: str = Field(..., description="日期")
    main_inflow: float = Field(..., description="主力流入")
    main_outflow: float = Field(..., description="主力流出")
    main_net: float = Field(..., description="主力净流入")
    retail_inflow: float = Field(..., description="散户流入")
    retail_outflow: float = Field(..., description="散户流出")
    retail_net: float = Field(..., description="散户净流入")
    total_inflow: float = Field(..., description="总流入")
    total_outflow: float = Field(..., description="总流出")
    total_net: float = Field(..., description="净流入")


class CapitalFlowListResponse(BaseModel):
    """资金流向列表响应"""
    stock_code: str = Field(..., description="股票代码")
    data: List[CapitalFlowDataResponse] = Field(..., description="资金流向数据列表")


class CapitalDistributionResponse(BaseModel):
    """资金分布响应"""
    stock_code: str = Field(..., description="股票代码")
    super_large: dict = Field(..., description="超大单（流入/流出/净流入）")
    large: dict = Field(..., description="大单（流入/流出/净流入）")
    medium: dict = Field(..., description="中单（流入/流出/净流入）")
    small: dict = Field(..., description="小单（流入/流出/净流入）")


# ============ 公司信息响应模型 ============

class CompanyProfileResponse(BaseModel):
    """公司简介响应"""
    name: str = Field(..., description="公司名称")
    english_name: str = Field(..., description="英文名称")
    industry: str = Field(..., description="所属行业")
    list_date: str = Field(..., description="上市日期")
    total_shares: float = Field(..., description="总股本")
    circulating_shares: float = Field(..., description="流通股本")
    description: str = Field(..., description="公司简介")
    main_business: str = Field(..., description="主营业务")
    registered_capital: float = Field(..., description="注册资本")
    employees: int = Field(..., description="员工人数")
    province: str = Field(..., description="所在省份")
    city: str = Field(..., description="所在城市")
    website: str = Field(..., description="公司网站")


class ShareholderResponse(BaseModel):
    """股东信息响应"""
    name: str = Field(..., description="股东名称")
    shares: float = Field(..., description="持股数量")
    percentage: float = Field(..., description="持股比例")
    nature: str = Field(..., description="股东性质")


class ShareholderListResponse(BaseModel):
    """股东列表响应"""
    stock_code: str = Field(..., description="股票代码")
    shareholders: List[ShareholderResponse] = Field(..., description="股东列表")


# ============ 资讯响应模型 ============

class StockNewsResponse(BaseModel):
    """股票新闻响应"""
    id: str = Field(..., description="新闻ID")
    title: str = Field(..., description="新闻标题")
    source: str = Field(..., description="来源")
    publish_time: str = Field(..., description="发布时间")
    url: str = Field(..., description="链接")
    sentiment: str = Field(..., description="情感（positive/negative/neutral）")
    summary: str = Field(..., description="摘要")


class StockNewsListResponse(BaseModel):
    """股票新闻列表响应"""
    stock_code: str = Field(..., description="股票代码")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页条数")
    data: List[StockNewsResponse] = Field(..., description="新闻列表")


class AnalystRatingResponse(BaseModel):
    """机构评级响应"""
    institution: str = Field(..., description="机构名称")
    analyst: str = Field(..., description="分析师")
    rating: str = Field(..., description="评级")
    target_price: float = Field(..., description="目标价")
    date: str = Field(..., description="日期")


class AnalystRatingListResponse(BaseModel):
    """机构评级列表响应"""
    stock_code: str = Field(..., description="股票代码")
    ratings: List[AnalystRatingResponse] = Field(..., description="评级列表")


# ============ 财务数据响应模型 ============

class FinancialMetricsResponse(BaseModel):
    """财务指标响应"""
    report_date: str = Field(..., description="报告期")
    revenue: float = Field(..., description="营业收入")
    revenue_yoy: float = Field(..., description="营收同比")
    net_profit: float = Field(..., description="净利润")
    net_profit_yoy: float = Field(..., description="净利润同比")
    gross_margin: float = Field(..., description="毛利率")
    net_margin: float = Field(..., description="净利率")
    roe: float = Field(..., description="净资产收益率")
    eps: float = Field(..., description="每股收益")
    bps: float = Field(..., description="每股净资产")


class FinancialMetricsListResponse(BaseModel):
    """财务指标列表响应"""
    stock_code: str = Field(..., description="股票代码")
    report_type: str = Field(..., description="报告类型")
    data: List[FinancialMetricsResponse] = Field(..., description="财务指标列表")


class BalanceSheetResponse(BaseModel):
    """资产负债表响应"""
    report_date: str = Field(..., description="报告期")
    total_assets: float = Field(..., description="总资产")
    total_liabilities: float = Field(..., description="总负债")
    total_equity: float = Field(..., description="股东权益")
    current_assets: float = Field(..., description="流动资产")
    current_liabilities: float = Field(..., description="流动负债")
    cash_and_equivalents: float = Field(..., description="货币资金")


class BalanceSheetListResponse(BaseModel):
    """资产负债表列表响应"""
    stock_code: str = Field(..., description="股票代码")
    data: List[BalanceSheetResponse] = Field(..., description="资产负债表列表")


class CashFlowResponse(BaseModel):
    """现金流量表响应"""
    report_date: str = Field(..., description="报告期")
    operating_cash_flow: float = Field(..., description="经营活动现金流")
    investing_cash_flow: float = Field(..., description="投资活动现金流")
    financing_cash_flow: float = Field(..., description="筹资活动现金流")
    net_cash_flow: float = Field(..., description="现金净流量")


class CashFlowListResponse(BaseModel):
    """现金流量表列表响应"""
    stock_code: str = Field(..., description="股票代码")
    data: List[CashFlowResponse] = Field(..., description="现金流量表列表")


# ============ 错误处理装饰器 ============

def handle_stock_errors(func):
    """股票API错误处理装饰器"""
    from functools import wraps
    
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except StockNotFoundError as e:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": e.error_code,
                    "message": e.message,
                    "stock_code": e.stock_code,
                },
            )
        except StockDataError as e:
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": e.error_code,
                    "message": e.message,
                    "stock_code": e.stock_code,
                },
            )
        except Exception as e:
            logger.exception(f"Unexpected error in stock API: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "INTERNAL_ERROR",
                    "message": "服务器内部错误，请稍后重试",
                },
            )
    return wrapper


# ============ API端点 ============

@router.get(
    "/{stock_code}/info",
    response_model=StockBasicInfoResponse,
    summary="获取股票基本信息",
    description="获取指定股票的基本信息，包括代码、名称、市场、行业、上市日期等",
)
@handle_stock_errors
async def get_stock_info(
    stock_code: str,
    db: Session = Depends(get_db),
) -> StockBasicInfoResponse:
    """获取股票基本信息
    
    Args:
        stock_code: 股票代码（6位数字）
        
    Returns:
        StockBasicInfoResponse: 股票基本信息
    """
    # 尝试从缓存获取
    cached = cache_service.get_stock_info(stock_code)
    if cached:
        logger.debug(f"股票信息缓存命中: {stock_code}")
        return StockBasicInfoResponse(**cached)
    
    # 从AkShare获取
    service = StockDataService(db)
    info = await service.get_stock_info(stock_code)
    
    result = StockBasicInfoResponse(
        code=info.code,
        name=info.name,
        market=info.market,
        industry=info.industry,
        list_date=info.list_date,
    )
    
    # 存入缓存
    cache_service.set_stock_info(stock_code, result.model_dump())
    
    return result


@router.get(
    "/{stock_code}/quote",
    response_model=StockRealtimeQuoteResponse,
    summary="获取实时行情",
    description="获取指定股票的实时行情数据，包括价格、涨跌、成交量等",
)
@handle_stock_errors
async def get_stock_quote(
    stock_code: str,
    db: Session = Depends(get_db),
) -> StockRealtimeQuoteResponse:
    """获取实时行情
    
    Args:
        stock_code: 股票代码（6位数字）
        
    Returns:
        StockRealtimeQuoteResponse: 实时行情数据
    """
    # 尝试从缓存获取（实时行情缓存30秒）
    cached = cache_service.get_stock_quote(stock_code)
    if cached:
        logger.debug(f"实时行情缓存命中: {stock_code}")
        return StockRealtimeQuoteResponse(**cached)
    
    # 从AkShare获取
    service = StockDataService(db)
    quote = await service.get_realtime_quote(stock_code)
    
    result = StockRealtimeQuoteResponse(
        price=quote.price,
        change=quote.change,
        change_pct=quote.change_pct,
        open=quote.open,
        high=quote.high,
        low=quote.low,
        prev_close=quote.prev_close,
        volume=quote.volume,
        amount=quote.amount,
        turnover_rate=quote.turnover_rate,
        pe=quote.pe,
        pb=quote.pb,
        market_cap=quote.market_cap,
        updated_at=quote.updated_at,
    )
    
    # 存入缓存
    cache_service.set_stock_quote(stock_code, result.model_dump())
    
    return result


@router.get(
    "/{stock_code}/kline",
    response_model=KLineListResponse,
    summary="获取K线数据",
    description="获取指定股票的K线历史数据，支持日K、周K、月K周期",
)
@handle_stock_errors
async def get_stock_kline(
    stock_code: str,
    period: str = Query(
        default="daily",
        description="周期类型: daily(日K), weekly(周K), monthly(月K)",
        pattern="^(daily|weekly|monthly)$",
    ),
    start_date: Optional[str] = Query(
        default=None,
        description="开始日期 (YYYY-MM-DD)",
        pattern="^\\d{4}-\\d{2}-\\d{2}$",
    ),
    end_date: Optional[str] = Query(
        default=None,
        description="结束日期 (YYYY-MM-DD)",
        pattern="^\\d{4}-\\d{2}-\\d{2}$",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="返回数据条数限制",
    ),
    db: Session = Depends(get_db),
) -> KLineListResponse:
    """获取K线数据
    
    Args:
        stock_code: 股票代码（6位数字）
        period: 周期类型 (daily/weekly/monthly)
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        limit: 返回数据条数限制
        
    Returns:
        KLineListResponse: K线数据列表
    """
    # K线数据只缓存默认参数的请求
    if start_date is None and end_date is None and limit == 100:
        cached = cache_service.get_stock_kline(stock_code, period)
        if cached:
            logger.debug(f"K线数据缓存命中: {stock_code}:{period}")
            return KLineListResponse(
                stock_code=stock_code,
                period=period,
                data=[KLineDataResponse(**k) for k in cached],
            )
    
    service = StockDataService(db)
    klines = await service.get_kline_data(
        stock_code=stock_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    
    data = [
        KLineDataResponse(
            date=k.date,
            open=k.open,
            high=k.high,
            low=k.low,
            close=k.close,
            volume=k.volume,
            amount=k.amount,
        )
        for k in klines
    ]
    
    # 缓存默认参数的请求
    if start_date is None and end_date is None and limit == 100:
        cache_service.set_stock_kline(stock_code, period, [d.model_dump() for d in data])
    
    return KLineListResponse(
        stock_code=stock_code,
        period=period,
        data=data,
    )


@router.get(
    "/{stock_code}/minute",
    response_model=MinuteDataListResponse,
    summary="获取分时数据",
    description="获取指定股票的分时数据，支持1/5/15/30/60分钟周期",
)
@handle_stock_errors
async def get_stock_minute_data(
    stock_code: str,
    period: str = Query(
        default="1",
        description="周期类型: 1(1分钟), 5(5分钟), 15(15分钟), 30(30分钟), 60(60分钟)",
        pattern="^(1|5|15|30|60)$",
    ),
    start_date: Optional[str] = Query(
        default=None,
        description="开始日期时间 (YYYY-MM-DD HH:MM:SS)",
    ),
    end_date: Optional[str] = Query(
        default=None,
        description="结束日期时间 (YYYY-MM-DD HH:MM:SS)",
    ),
    db: Session = Depends(get_db),
) -> MinuteDataListResponse:
    """获取分时数据

    Args:
        stock_code: 股票代码（6位数字）
        period: 周期类型 (1/5/15/30/60分钟)
        start_date: 开始日期时间 (YYYY-MM-DD HH:MM:SS)
        end_date: 结束日期时间 (YYYY-MM-DD HH:MM:SS)

    Returns:
        MinuteDataListResponse: 分时数据列表
    """
    service = StockDataService(db)
    minutes = await service.get_minute_data(
        stock_code=stock_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    data = [
        MinuteDataResponse(
            time=m.time,
            open=m.open,
            high=m.high,
            low=m.low,
            close=m.close,
            volume=m.volume,
            amount=m.amount,
            avg_price=m.avg_price,
        )
        for m in minutes
    ]

    return MinuteDataListResponse(
        stock_code=stock_code,
        period=period,
        data=data,
    )


# ============ 资金流向API端点 ============

@router.get(
    "/{stock_code}/capital-flow",
    response_model=CapitalFlowListResponse,
    summary="获取资金流向",
    description="获取指定股票的资金流向数据，包括主力和散户的流入流出",
)
@handle_stock_errors
async def get_capital_flow(
    stock_code: str,
    days: int = Query(
        default=5,
        ge=1,
        le=30,
        description="获取天数，默认5天",
    ),
    db: Session = Depends(get_db),
) -> CapitalFlowListResponse:
    """获取资金流向
    
    Args:
        stock_code: 股票代码（6位数字）
        days: 获取天数
        
    Returns:
        CapitalFlowListResponse: 资金流向数据列表
    """
    # 尝试从缓存获取
    cached = cache_service.get_capital_flow(stock_code)
    if cached:
        logger.debug(f"资金流向缓存命中: {stock_code}")
        return CapitalFlowListResponse(
            stock_code=stock_code,
            data=[CapitalFlowDataResponse(**f) for f in cached[:days]],
        )
    
    service = StockDataService(db)
    flows = await service.get_capital_flow(stock_code, days)
    
    data = [
        CapitalFlowDataResponse(
            date=f.date,
            main_inflow=f.main_inflow,
            main_outflow=f.main_outflow,
            main_net=f.main_net,
            retail_inflow=f.retail_inflow,
            retail_outflow=f.retail_outflow,
            retail_net=f.retail_net,
            total_inflow=f.total_inflow,
            total_outflow=f.total_outflow,
            total_net=f.total_net,
        )
        for f in flows
    ]
    
    # 存入缓存
    cache_service.set_capital_flow(stock_code, [d.model_dump() for d in data])
    
    return CapitalFlowListResponse(
        stock_code=stock_code,
        data=data,
    )


@router.get(
    "/{stock_code}/capital-distribution",
    response_model=CapitalDistributionResponse,
    summary="获取资金分布",
    description="获取指定股票的资金分布数据，按超大单、大单、中单、小单分类",
)
@handle_stock_errors
async def get_capital_distribution(
    stock_code: str,
    db: Session = Depends(get_db),
) -> CapitalDistributionResponse:
    """获取资金分布
    
    Args:
        stock_code: 股票代码（6位数字）
        
    Returns:
        CapitalDistributionResponse: 资金分布数据
    """
    # 尝试从缓存获取
    cached = cache_service.get_capital_distribution(stock_code)
    if cached:
        logger.debug(f"资金分布缓存命中: {stock_code}")
        return CapitalDistributionResponse(**cached)
    
    service = StockDataService(db)
    dist = await service.get_capital_distribution(stock_code)
    
    result = CapitalDistributionResponse(
        stock_code=stock_code,
        super_large={
            "inflow": dist.super_large_inflow,
            "outflow": dist.super_large_outflow,
            "net": dist.super_large_net,
        },
        large={
            "inflow": dist.large_inflow,
            "outflow": dist.large_outflow,
            "net": dist.large_net,
        },
        medium={
            "inflow": dist.medium_inflow,
            "outflow": dist.medium_outflow,
            "net": dist.medium_net,
        },
        small={
            "inflow": dist.small_inflow,
            "outflow": dist.small_outflow,
            "net": dist.small_net,
        },
    )
    
    # 存入缓存
    cache_service.set_capital_distribution(stock_code, result.model_dump())
    
    return result


# ============ 公司信息API端点 ============

@router.get(
    "/{stock_code}/profile",
    response_model=CompanyProfileResponse,
    summary="获取公司简介",
    description="获取指定股票的公司详细信息，包括公司名称、行业、主营业务等",
)
@handle_stock_errors
async def get_company_profile(
    stock_code: str,
    db: Session = Depends(get_db),
) -> CompanyProfileResponse:
    """获取公司简介
    
    Args:
        stock_code: 股票代码（6位数字）
        
    Returns:
        CompanyProfileResponse: 公司简介
    """
    # 尝试从缓存获取
    cached = cache_service.get_company_profile(stock_code)
    if cached:
        logger.debug(f"公司简介缓存命中: {stock_code}")
        return CompanyProfileResponse(**cached)
    
    service = StockDataService(db)
    profile = await service.get_company_profile(stock_code)
    
    result = CompanyProfileResponse(
        name=profile.name,
        english_name=profile.english_name,
        industry=profile.industry,
        list_date=profile.list_date,
        total_shares=profile.total_shares,
        circulating_shares=profile.circulating_shares,
        description=profile.description,
        main_business=profile.main_business,
        registered_capital=profile.registered_capital,
        employees=profile.employees,
        province=profile.province,
        city=profile.city,
        website=profile.website,
    )
    
    # 存入缓存
    cache_service.set_company_profile(stock_code, result.model_dump())
    
    return result


@router.get(
    "/{stock_code}/shareholders",
    response_model=ShareholderListResponse,
    summary="获取股东信息",
    description="获取指定股票的十大流通股东信息",
)
@handle_stock_errors
async def get_shareholders(
    stock_code: str,
    db: Session = Depends(get_db),
) -> ShareholderListResponse:
    """获取股东信息
    
    Args:
        stock_code: 股票代码（6位数字）
        
    Returns:
        ShareholderListResponse: 股东信息列表
    """
    # 尝试从缓存获取
    cached = cache_service.get_shareholders(stock_code)
    if cached:
        logger.debug(f"股东信息缓存命中: {stock_code}")
        return ShareholderListResponse(
            stock_code=stock_code,
            shareholders=[ShareholderResponse(**s) for s in cached],
        )
    
    service = StockDataService(db)
    shareholders = await service.get_shareholders(stock_code)
    
    data = [
        ShareholderResponse(
            name=s.name,
            shares=s.shares,
            percentage=s.percentage,
            nature=s.nature,
        )
        for s in shareholders
    ]
    
    # 存入缓存
    cache_service.set_shareholders(stock_code, [d.model_dump() for d in data])
    
    return ShareholderListResponse(
        stock_code=stock_code,
        shareholders=data,
    )



# ============ 资讯API端点 ============

@router.get(
    "/{stock_code}/news",
    response_model=StockNewsListResponse,
    summary="获取股票新闻",
    description="获取指定股票的相关新闻列表，包含情感分析",
)
@handle_stock_errors
async def get_stock_news(
    stock_code: str,
    page: int = Query(
        default=1,
        ge=1,
        description="页码，默认1",
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=50,
        description="每页条数，默认20",
    ),
    db: Session = Depends(get_db),
) -> StockNewsListResponse:
    """获取股票新闻
    
    Args:
        stock_code: 股票代码（6位数字）
        page: 页码
        page_size: 每页条数
        
    Returns:
        StockNewsListResponse: 新闻列表
    """
    # 尝试从缓存获取
    cached = cache_service.get_stock_news(stock_code, page)
    if cached:
        logger.debug(f"股票新闻缓存命中: {stock_code}:{page}")
        return StockNewsListResponse(
            stock_code=stock_code,
            page=page,
            page_size=page_size,
            data=[StockNewsResponse(**n) for n in cached[:page_size]],
        )
    
    service = StockDataService(db)
    news_list = await service.get_stock_news(stock_code, page, page_size)
    
    data = [
        StockNewsResponse(
            id=n.id,
            title=n.title,
            source=n.source,
            publish_time=n.publish_time,
            url=n.url,
            sentiment=n.sentiment,
            summary=n.summary,
        )
        for n in news_list
    ]
    
    # 存入缓存
    cache_service.set_stock_news(stock_code, page, [d.model_dump() for d in data])
    
    return StockNewsListResponse(
        stock_code=stock_code,
        page=page,
        page_size=page_size,
        data=data,
    )


@router.get(
    "/{stock_code}/analyst-ratings",
    response_model=AnalystRatingListResponse,
    summary="获取机构评级",
    description="获取指定股票的机构评级信息",
)
@handle_stock_errors
async def get_analyst_ratings(
    stock_code: str,
    db: Session = Depends(get_db),
) -> AnalystRatingListResponse:
    """获取机构评级
    
    Args:
        stock_code: 股票代码（6位数字）
        
    Returns:
        AnalystRatingListResponse: 机构评级列表
    """
    # 尝试从缓存获取
    cached = cache_service.get_analyst_ratings(stock_code)
    if cached:
        logger.debug(f"机构评级缓存命中: {stock_code}")
        return AnalystRatingListResponse(
            stock_code=stock_code,
            ratings=[AnalystRatingResponse(**r) for r in cached],
        )
    
    service = StockDataService(db)
    ratings = await service.get_analyst_ratings(stock_code)
    
    data = [
        AnalystRatingResponse(
            institution=r.institution,
            analyst=r.analyst,
            rating=r.rating,
            target_price=r.target_price,
            date=r.date,
        )
        for r in ratings
    ]
    
    # 存入缓存
    cache_service.set_analyst_ratings(stock_code, [d.model_dump() for d in data])
    
    return AnalystRatingListResponse(
        stock_code=stock_code,
        ratings=data,
    )


# ============ 财务数据API端点 ============

@router.get(
    "/{stock_code}/financials",
    response_model=FinancialMetricsListResponse,
    summary="获取财务指标",
    description="获取指定股票的财务分析指标，包括营收、利润、毛利率等",
)
@handle_stock_errors
async def get_financials(
    stock_code: str,
    report_type: str = Query(
        default="quarterly",
        description="报告类型: quarterly(季报), annual(年报)",
        pattern="^(quarterly|annual)$",
    ),
    periods: int = Query(
        default=4,
        ge=1,
        le=20,
        description="获取期数，默认4期",
    ),
    db: Session = Depends(get_db),
) -> FinancialMetricsListResponse:
    """获取财务指标
    
    Args:
        stock_code: 股票代码（6位数字）
        report_type: 报告类型 (quarterly/annual)
        periods: 获取期数
        
    Returns:
        FinancialMetricsListResponse: 财务指标列表
    """
    # 尝试从缓存获取
    cached = cache_service.get_financials(stock_code, report_type)
    if cached:
        logger.debug(f"财务指标缓存命中: {stock_code}:{report_type}")
        return FinancialMetricsListResponse(
            stock_code=stock_code,
            report_type=report_type,
            data=[FinancialMetricsResponse(**m) for m in cached[:periods]],
        )
    
    service = StockDataService(db)
    metrics = await service.get_financial_metrics(stock_code, report_type, periods)
    
    data = [
        FinancialMetricsResponse(
            report_date=m.report_date,
            revenue=m.revenue,
            revenue_yoy=m.revenue_yoy,
            net_profit=m.net_profit,
            net_profit_yoy=m.net_profit_yoy,
            gross_margin=m.gross_margin,
            net_margin=m.net_margin,
            roe=m.roe,
            eps=m.eps,
            bps=m.bps,
        )
        for m in metrics
    ]
    
    # 存入缓存
    cache_service.set_financials(stock_code, report_type, [d.model_dump() for d in data])
    
    return FinancialMetricsListResponse(
        stock_code=stock_code,
        report_type=report_type,
        data=data,
    )


@router.get(
    "/{stock_code}/balance-sheet",
    response_model=BalanceSheetListResponse,
    summary="获取资产负债表",
    description="获取指定股票的资产负债表数据",
)
@handle_stock_errors
async def get_balance_sheet(
    stock_code: str,
    periods: int = Query(
        default=4,
        ge=1,
        le=20,
        description="获取期数，默认4期",
    ),
    db: Session = Depends(get_db),
) -> BalanceSheetListResponse:
    """获取资产负债表
    
    Args:
        stock_code: 股票代码（6位数字）
        periods: 获取期数
        
    Returns:
        BalanceSheetListResponse: 资产负债表列表
    """
    # 尝试从缓存获取
    cached = cache_service.get_balance_sheet(stock_code)
    if cached:
        logger.debug(f"资产负债表缓存命中: {stock_code}")
        return BalanceSheetListResponse(
            stock_code=stock_code,
            data=[BalanceSheetResponse(**b) for b in cached[:periods]],
        )
    
    service = StockDataService(db)
    balance_sheets = await service.get_balance_sheet(stock_code, periods)
    
    data = [
        BalanceSheetResponse(
            report_date=b.report_date,
            total_assets=b.total_assets,
            total_liabilities=b.total_liabilities,
            total_equity=b.total_equity,
            current_assets=b.current_assets,
            current_liabilities=b.current_liabilities,
            cash_and_equivalents=b.cash_and_equivalents,
        )
        for b in balance_sheets
    ]
    
    # 存入缓存
    cache_service.set_balance_sheet(stock_code, [d.model_dump() for d in data])
    
    return BalanceSheetListResponse(
        stock_code=stock_code,
        data=data,
    )


@router.get(
    "/{stock_code}/cash-flow",
    response_model=CashFlowListResponse,
    summary="获取现金流量表",
    description="获取指定股票的现金流量表数据",
)
@handle_stock_errors
async def get_cash_flow(
    stock_code: str,
    periods: int = Query(
        default=4,
        ge=1,
        le=20,
        description="获取期数，默认4期",
    ),
    db: Session = Depends(get_db),
) -> CashFlowListResponse:
    """获取现金流量表
    
    Args:
        stock_code: 股票代码（6位数字）
        periods: 获取期数
        
    Returns:
        CashFlowListResponse: 现金流量表列表
    """
    # 尝试从缓存获取
    cached = cache_service.get_cash_flow(stock_code)
    if cached:
        logger.debug(f"现金流量表缓存命中: {stock_code}")
        return CashFlowListResponse(
            stock_code=stock_code,
            data=[CashFlowResponse(**c) for c in cached[:periods]],
        )
    
    service = StockDataService(db)
    cash_flows = await service.get_cash_flow(stock_code, periods)
    
    data = [
        CashFlowResponse(
            report_date=c.report_date,
            operating_cash_flow=c.operating_cash_flow,
            investing_cash_flow=c.investing_cash_flow,
            financing_cash_flow=c.financing_cash_flow,
            net_cash_flow=c.net_cash_flow,
        )
        for c in cash_flows
    ]
    
    # 存入缓存
    cache_service.set_cash_flow(stock_code, [d.model_dump() for d in data])
    
    return CashFlowListResponse(
        stock_code=stock_code,
        data=data,
    )


# ============ AI分析响应模型 ============

class TechnicalIndicatorResponse(BaseModel):
    """技术指标响应"""
    name: str = Field(..., description="指标名称")
    value: str = Field(..., description="指标值")
    signal: str = Field(..., description="信号（positive/negative/neutral）")


class TechnicalAnalysisResponse(BaseModel):
    """技术面分析响应"""
    summary: str = Field(..., description="技术面分析总结")
    trend: str = Field(..., description="趋势（bullish/bearish/neutral）")
    indicators: List[TechnicalIndicatorResponse] = Field(default_factory=list, description="技术指标列表")


class FundamentalAnalysisResponse(BaseModel):
    """基本面分析响应"""
    summary: str = Field(..., description="基本面分析总结")
    valuation: str = Field(..., description="估值（undervalued/fair/overvalued）")
    highlights: List[str] = Field(default_factory=list, description="亮点")
    concerns: List[str] = Field(default_factory=list, description="风险点")


class SentimentAnalysisResponse(BaseModel):
    """舆情分析响应"""
    summary: str = Field(..., description="舆情分析总结")
    sentiment: str = Field(..., description="情感（positive/negative/neutral）")
    news_highlights: List[str] = Field(default_factory=list, description="新闻要点")


class AIAnalysisResultResponse(BaseModel):
    """AI分析结果响应"""
    stock_code: str = Field(..., description="股票代码")
    stock_name: str = Field(..., description="股票名称")
    analysis_time: str = Field(..., description="分析时间")
    overall_rating: str = Field(..., description="综合评级（strong_buy/buy/neutral/cautious/avoid）")
    rating_score: int = Field(..., description="评分（1-5）")
    technical_analysis: TechnicalAnalysisResponse = Field(..., description="技术面分析")
    fundamental_analysis: FundamentalAnalysisResponse = Field(..., description="基本面分析")
    sentiment_analysis: SentimentAnalysisResponse = Field(..., description="舆情分析")
    investment_points: List[str] = Field(default_factory=list, description="投资要点")
    risk_warnings: List[str] = Field(default_factory=list, description="风险提示")
    conclusion: str = Field(..., description="综合结论")


class AIAnalysisRequest(BaseModel):
    """AI分析请求"""
    force_refresh: bool = Field(default=False, description="是否强制刷新（忽略缓存）")


# ============ AI分析错误处理 ============

from app.core.exceptions import AIAnalysisError


def handle_ai_analysis_errors(func):
    """AI分析API错误处理装饰器"""
    from functools import wraps
    
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except AIAnalysisError as e:
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": e.error_code,
                    "message": e.message,
                    "stock_code": e.stock_code,
                },
            )
        except StockNotFoundError as e:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": e.error_code,
                    "message": e.message,
                    "stock_code": e.stock_code,
                },
            )
        except StockDataError as e:
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": e.error_code,
                    "message": e.message,
                    "stock_code": e.stock_code,
                },
            )
        except Exception as e:
            logger.exception(f"Unexpected error in AI analysis API: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "INTERNAL_ERROR",
                    "message": "服务器内部错误，请稍后重试",
                },
            )
    return wrapper


# ============ AI分析API端点 ============

@router.post(
    "/{stock_code}/ai-analysis",
    response_model=AIAnalysisResultResponse,
    summary="生成AI分析报告",
    description="使用LLM生成指定股票的综合分析报告，包含技术面、基本面、舆情分析",
)
@handle_ai_analysis_errors
async def generate_ai_analysis(
    stock_code: str,
    request: AIAnalysisRequest = AIAnalysisRequest(),
    db: Session = Depends(get_db),
) -> AIAnalysisResultResponse:
    """生成AI分析报告
    
    Args:
        stock_code: 股票代码（6位数字）
        request: 分析请求参数
        
    Returns:
        AIAnalysisResultResponse: AI分析结果
    """
    from app.ai.stock_analysis import AIAnalysisService
    from app.ai.llm_client import MultiProtocolLLMClient
    from app.db.repositories import LLMProviderRepository
    
    # 获取默认LLM渠道
    provider_repo = LLMProviderRepository(db)
    providers = provider_repo.get_all_active()
    
    if not providers:
        raise AIAnalysisError(
            message="没有可用的LLM渠道，请先配置LLM渠道",
            stock_code=stock_code,
        )
    
    # 使用第一个活跃的渠道
    provider = providers[0]
    
    # 创建LLM客户端
    from app.models.enums import LLMProtocol
    llm_client = MultiProtocolLLMClient(
        protocol=LLMProtocol(provider.protocol),
        api_base=provider.api_url,
        api_key=provider.api_key,
        provider_id=provider.provider_id,
    )
    
    try:
        # 创建AI分析服务
        service = AIAnalysisService(db, llm_client)
        
        # 生成分析
        result = await service.generate_analysis(
            stock_code=stock_code,
            force_refresh=request.force_refresh,
        )
        
        # 转换为响应模型
        return AIAnalysisResultResponse(
            stock_code=result.stock_code,
            stock_name=result.stock_name,
            analysis_time=result.analysis_time,
            overall_rating=result.overall_rating,
            rating_score=result.rating_score,
            technical_analysis=TechnicalAnalysisResponse(
                summary=result.technical_analysis.summary,
                trend=result.technical_analysis.trend,
                indicators=[
                    TechnicalIndicatorResponse(
                        name=i.name,
                        value=i.value,
                        signal=i.signal,
                    )
                    for i in result.technical_analysis.indicators
                ],
            ),
            fundamental_analysis=FundamentalAnalysisResponse(
                summary=result.fundamental_analysis.summary,
                valuation=result.fundamental_analysis.valuation,
                highlights=result.fundamental_analysis.highlights,
                concerns=result.fundamental_analysis.concerns,
            ),
            sentiment_analysis=SentimentAnalysisResponse(
                summary=result.sentiment_analysis.summary,
                sentiment=result.sentiment_analysis.sentiment,
                news_highlights=result.sentiment_analysis.news_highlights,
            ),
            investment_points=result.investment_points,
            risk_warnings=result.risk_warnings,
            conclusion=result.conclusion,
        )
    finally:
        await llm_client.close()


@router.get(
    "/{stock_code}/ai-analysis",
    response_model=Optional[AIAnalysisResultResponse],
    summary="获取缓存的AI分析报告",
    description="获取指定股票的缓存AI分析报告，如果没有缓存或已过期则返回null",
)
@handle_ai_analysis_errors
async def get_ai_analysis(
    stock_code: str,
    db: Session = Depends(get_db),
) -> Optional[AIAnalysisResultResponse]:
    """获取缓存的AI分析报告
    
    Args:
        stock_code: 股票代码（6位数字）
        
    Returns:
        AIAnalysisResultResponse 或 None
    """
    from app.ai.stock_analysis import AIAnalysisService
    
    # 创建AI分析服务（不需要LLM客户端，只是获取缓存）
    service = AIAnalysisService(db)
    
    # 获取缓存的分析
    result = await service.get_cached_analysis(stock_code)
    
    if result is None:
        return None
    
    # 转换为响应模型
    return AIAnalysisResultResponse(
        stock_code=result.stock_code,
        stock_name=result.stock_name,
        analysis_time=result.analysis_time,
        overall_rating=result.overall_rating,
        rating_score=result.rating_score,
        technical_analysis=TechnicalAnalysisResponse(
            summary=result.technical_analysis.summary,
            trend=result.technical_analysis.trend,
            indicators=[
                TechnicalIndicatorResponse(
                    name=i.name,
                    value=i.value,
                    signal=i.signal,
                )
                for i in result.technical_analysis.indicators
            ],
        ),
        fundamental_analysis=FundamentalAnalysisResponse(
            summary=result.fundamental_analysis.summary,
            valuation=result.fundamental_analysis.valuation,
            highlights=result.fundamental_analysis.highlights,
            concerns=result.fundamental_analysis.concerns,
        ),
        sentiment_analysis=SentimentAnalysisResponse(
            summary=result.sentiment_analysis.summary,
            sentiment=result.sentiment_analysis.sentiment,
            news_highlights=result.sentiment_analysis.news_highlights,
        ),
        investment_points=result.investment_points,
        risk_warnings=result.risk_warnings,
        conclusion=result.conclusion,
    )
