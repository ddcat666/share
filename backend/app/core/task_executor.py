"""
任务执行器模块

负责执行系统任务并记录日志。

实现需求:
- 3.1, 3.2: 支持多种任务类型（agent_decision, quote_sync, market_refresh）
- 5.2: 展示运行时间、执行状态、耗时
- 5.3: 展示各Agent的运行情况（成功/失败/跳过）
- 5.4: Agent执行失败时显示失败原因
- 6.1: 仅交易日运行的任务在非交易日跳过执行
- 6.2: 任务执行被跳过时记录跳过原因到日志
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

from sqlalchemy.orm import Session

from app.db.models import SystemTaskModel, SystemTaskLogModel, ModelAgentModel
from app.models.enums import TaskStatus, TaskLogStatus, AgentStatus, TaskType
from app.core.timezone import now
from app.core.trading_rules import is_trading_day

logger = logging.getLogger(__name__)


class TaskExecutor:
    """
    任务执行器
    
    负责执行系统任务并记录日志。
    支持多种任务类型的分发执行。
    """
    
    def __init__(self, db: Session, decision_callback=None):
        """
        初始化任务执行器
        
        Args:
            db: 数据库会话
            decision_callback: Agent决策回调函数，接收agent_id参数
        """
        self.db = db
        self._decision_callback = decision_callback
    
    def set_decision_callback(self, callback) -> None:
        """设置决策回调函数"""
        self._decision_callback = callback
    
    async def execute_task(self, task_id: str) -> SystemTaskLogModel:
        """
        执行任务并记录日志
        
        根据任务类型分发到不同的执行器。
        
        Args:
            task_id: 任务ID
            
        Returns:
            SystemTaskLogModel: 任务执行日志
        """
        # 获取任务
        task = self.db.query(SystemTaskModel).filter(
            SystemTaskModel.task_id == task_id
        ).first()
        
        if not task:
            raise ValueError(f"任务不存在: {task_id}")
        
        # 直接使用数据库中的 task_type 和 config 字段
        # 不再从 agent_ids 解析（旧的兼容逻辑已废弃）
        task_type_str = task.task_type or "agent_decision"
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.AGENT_DECISION
        
        agent_ids = task.agent_ids or ["all"]
        config = task.config or {}
        
        # 创建日志记录
        started_at = now()
        log = SystemTaskLogModel(
            task_id=task_id,
            started_at=started_at,
            status=TaskLogStatus.RUNNING.value,
            agent_results=[],
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        
        try:
            # 检查是否应该跳过
            should_skip, skip_reason = self._should_skip(task)
            
            if should_skip:
                # 记录跳过
                log.status = TaskLogStatus.SKIPPED.value
                log.skip_reason = skip_reason
                log.completed_at = now()
                self.db.commit()
                logger.info(f"任务 {task.name} 被跳过: {skip_reason}")
                return log
            
            # 根据任务类型分发执行
            if task_type == TaskType.AGENT_DECISION:
                agent_results = await self._execute_agents(agent_ids)
                log.agent_results = agent_results
                
                # 判断整体状态
                failed_count = sum(1 for r in agent_results if r.get("status") == "failed")
                if failed_count == len(agent_results) and len(agent_results) > 0:
                    log.status = TaskLogStatus.FAILED.value
                    log.error_message = "所有Agent执行失败"
                elif failed_count > 0:
                    log.status = TaskLogStatus.SUCCESS.value  # 部分成功也算成功
                else:
                    log.status = TaskLogStatus.SUCCESS.value
                    
            elif task_type == TaskType.QUOTE_SYNC:
                result = await self._execute_quote_sync(config)
                log.agent_results = [result]
                log.status = TaskLogStatus.SUCCESS.value if result.get("status") == "success" else TaskLogStatus.FAILED.value
                if result.get("error_message"):
                    log.error_message = result.get("error_message")
                    
            elif task_type == TaskType.MARKET_REFRESH:
                result = await self._execute_market_refresh(config)
                log.agent_results = [result]
                log.status = TaskLogStatus.SUCCESS.value if result.get("status") == "success" else TaskLogStatus.FAILED.value
                if result.get("error_message"):
                    log.error_message = result.get("error_message")
            else:
                raise ValueError(f"未知的任务类型: {task_type}")
            
            log.completed_at = now()
            self.db.commit()
            logger.info(f"任务 {task.name} 执行完成, 状态: {log.status}")
            return log
            
        except Exception as e:
            # 记录错误
            log.status = TaskLogStatus.FAILED.value
            log.error_message = str(e)
            log.completed_at = now()
            self.db.commit()
            logger.error(f"任务 {task.name} 执行失败: {e}")
            return log
    
    async def _execute_quote_sync(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """执行行情同步任务
        
        Args:
            config: 任务配置
                - stock_codes: 股票代码列表（空表示同步热门股票）
                - days: 同步天数
                - force_full: 是否强制全量同步
                
        Returns:
            执行结果字典
        """
        started_at = now()
        
        try:
            from app.data.quote_service import QuoteService
            
            quote_service = QuoteService(self.db)
            
            stock_codes = config.get("stock_codes", [])
            # 从任务中获取同步股票行情天数，默认同步近7天的行情
            days = config.get("days", 7)
            force_full = config.get("force_full", False)
            
            if stock_codes:
                # 同步指定股票
                result = await quote_service.sync_specific_stocks(stock_codes, days)
            else:
                # 智能同步
                result = await quote_service.sync_quotes(force_full)
            
            completed_at = now()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            
            return {
                "task_type": "quote_sync",
                "status": "success" if result.success else "failed",
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "success_count": result.success_count,
                "fail_count": result.fail_count,
                "message": result.message,
                "error_message": None if result.success else result.message,
            }
            
        except Exception as e:
            completed_at = now()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            
            logger.error(f"行情同步任务执行失败: {e}")
            
            return {
                "task_type": "quote_sync",
                "status": "failed",
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "error_message": str(e),
            }
    
    async def _execute_market_refresh(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """执行市场数据刷新任务
        
        Args:
            config: 任务配置
                - refresh_types: 刷新类型列表 ["sentiment", "indices", "hot_stocks"]
                
        Returns:
            执行结果字典
        """
        started_at = now()
        
        try:
            from app.data.market_service import MarketDataService
            from app.data.quote_service import QuoteService
            
            # 创建服务实例，注入 QuoteService
            quote_service = QuoteService(self.db)
            market_service = MarketDataService(self.db, quote_service)
            
            refresh_types = config.get("refresh_types", ["sentiment", "indices", "hot_stocks"])
            
            results = {}
            
            if "sentiment" in refresh_types or not refresh_types:
                results["sentiment"] = await market_service.refresh_market_sentiment()
            
            if "indices" in refresh_types or not refresh_types:
                results["indices"] = await market_service.refresh_index_overview()
            
            if "hot_stocks" in refresh_types or not refresh_types:
                results["hot_stocks"] = await market_service.refresh_hot_stocks()
            
            completed_at = now()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            
            # 判断整体状态
            all_success = all(results.values())
            
            return {
                "task_type": "market_refresh",
                "status": "success" if all_success else "failed",
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "results": results,
                "error_message": None if all_success else "部分刷新失败",
            }
            
        except Exception as e:
            completed_at = now()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            
            logger.error(f"市场数据刷新任务执行失败: {e}")
            
            return {
                "task_type": "market_refresh",
                "status": "failed",
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "error_message": str(e),
            }
    
    def _should_skip(self, task: SystemTaskModel) -> Tuple[bool, Optional[str]]:
        """
        判断是否应跳过执行
        
        Args:
            task: 任务模型
            
        Returns:
            Tuple[bool, Optional[str]]: (是否跳过, 跳过原因)
        """
        # 检查任务状态
        if task.status == TaskStatus.PAUSED.value:
            return True, "任务已暂停"
        
        # 检查交易日
        if task.trading_day_only:
            current_date = now().date()
            if not is_trading_day(current_date):
                weekday = current_date.weekday()
                weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                return True, f"非交易日（{current_date.strftime('%Y-%m-%d')} {weekday_names[weekday]}）"
        
        return False, None
    
    async def _execute_agents(self, agent_ids: List[str]) -> List[Dict[str, Any]]:
        """
        执行Agent决策
        
        Args:
            agent_ids: Agent ID列表，["all"]表示全部Agent
            
        Returns:
            List[Dict[str, Any]]: Agent执行结果列表
        """
        # 获取要执行的Agent列表
        if agent_ids == ["all"] or "all" in agent_ids:
            agents = self.db.query(ModelAgentModel).filter(
                ModelAgentModel.status == AgentStatus.ACTIVE.value
            ).all()
        else:
            agents = self.db.query(ModelAgentModel).filter(
                ModelAgentModel.agent_id.in_(agent_ids),
                ModelAgentModel.status == AgentStatus.ACTIVE.value
            ).all()
        
        if not agents:
            logger.warning("没有找到可执行的Agent")
            return []
        
        results = []
        
        # 并发执行所有Agent
        tasks = [
            self._execute_single_agent(agent)
            for agent in agents
        ]
        
        agent_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(agent_results):
            agent = agents[i]
            if isinstance(result, Exception):
                results.append({
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "status": "failed",
                    "started_at": None,
                    "completed_at": None,
                    "duration_ms": None,
                    "error_message": str(result),
                })
            else:
                results.append(result)
        
        return results
    
    async def _execute_single_agent(self, agent: ModelAgentModel) -> Dict[str, Any]:
        """
        执行单个Agent的决策
        
        Args:
            agent: Agent模型
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        started_at = now()
        
        try:
            # 检查Agent状态
            if agent.status != AgentStatus.ACTIVE.value:
                return {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "status": "skipped",
                    "started_at": started_at.isoformat(),
                    "completed_at": now().isoformat(),
                    "duration_ms": 0,
                    "error_message": f"Agent状态不是活跃: {agent.status}",
                }
            
            # 调用决策回调
            if self._decision_callback is None:
                raise ValueError("决策回调函数未设置")
            
            result = self._decision_callback(agent.agent_id)
            
            # 如果是协程，等待执行
            if asyncio.iscoroutine(result):
                result = await result
            
            completed_at = now()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            
            return {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "status": "success",
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "error_message": None,
            }
            
        except Exception as e:
            completed_at = now()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            
            logger.error(f"Agent {agent.name} 执行失败: {e}")
            
            return {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "status": "failed",
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "error_message": str(e),
            }


def is_non_trading_day(date_to_check: datetime) -> Tuple[bool, Optional[str]]:
    """
    检查指定日期是否为非交易日
    
    Args:
        date_to_check: 要检查的日期时间
        
    Returns:
        Tuple[bool, Optional[str]]: (是否为非交易日, 原因)
    """
    check_date = date_to_check.date() if isinstance(date_to_check, datetime) else date_to_check
    
    if not is_trading_day(check_date):
        weekday = check_date.weekday()
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return True, f"非交易日（{check_date.strftime('%Y-%m-%d')} {weekday_names[weekday]}）"
    
    return False, None
