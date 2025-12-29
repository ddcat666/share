"""分布式锁模块

基于 Redis 实现的分布式锁，用于防止并发操作导致数据错乱。

主要用途：
- Agent 决策执行锁：防止同一 Agent 同时执行多个决策
- 持仓更新锁：防止并发更新同一 Agent 的持仓数据
- 余额更新锁：防止并发更新同一 Agent 的现金余额
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from app.core.cache import get_redis

logger = logging.getLogger(__name__)


class LockKeys:
    """锁键前缀常量"""
    # Agent 决策锁
    AGENT_DECISION = "lock:agent:decision:"
    # Agent 持仓锁
    AGENT_POSITION = "lock:agent:position:"
    # Agent 余额锁
    AGENT_BALANCE = "lock:agent:balance:"
    # Agent 全局锁（决策+持仓+余额）
    AGENT_GLOBAL = "lock:agent:global:"


class LockTTL:
    """锁过期时间配置（秒）"""
    # 决策锁：5分钟（LLM 调用可能较慢）
    AGENT_DECISION = 300
    # 持仓锁：30秒
    AGENT_POSITION = 30
    # 余额锁：30秒
    AGENT_BALANCE = 30
    # 全局锁：5分钟
    AGENT_GLOBAL = 300


class LockAcquisitionError(Exception):
    """获取锁失败异常"""
    pass


class DistributedLock:
    """分布式锁实现
    
    使用 Redis SET NX EX 实现，支持：
    - 自动过期防止死锁
    - 唯一标识防止误释放
    - 可重入支持（同一持有者可重复获取）
    """
    
    def __init__(
        self,
        key: str,
        ttl: int = 30,
        retry_times: int = 3,
        retry_delay: float = 0.5,
    ):
        """
        初始化分布式锁
        
        Args:
            key: 锁的键名
            ttl: 锁的过期时间（秒）
            retry_times: 获取锁的重试次数
            retry_delay: 重试间隔（秒）
        """
        self.key = key
        self.ttl = ttl
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        self._lock_id = str(uuid.uuid4())
        self._redis = None
    
    @property
    def redis(self):
        """获取 Redis 客户端"""
        if self._redis is None:
            self._redis = get_redis()
        return self._redis
    
    def acquire(self, blocking: bool = True) -> bool:
        """
        获取锁
        
        Args:
            blocking: 是否阻塞等待
            
        Returns:
            bool: 是否成功获取锁
        """
        for attempt in range(self.retry_times if blocking else 1):
            try:
                # SET key value NX EX ttl
                result = self.redis.set(
                    self.key,
                    self._lock_id,
                    nx=True,
                    ex=self.ttl,
                )
                if result:
                    logger.debug(f"获取锁成功: {self.key} (id={self._lock_id[:8]})")
                    return True
                
                if blocking and attempt < self.retry_times - 1:
                    logger.debug(f"获取锁失败，重试中: {self.key} (attempt={attempt + 1})")
                    time.sleep(self.retry_delay)
                    
            except Exception as e:
                logger.error(f"获取锁异常: {self.key}, error={e}")
                if blocking and attempt < self.retry_times - 1:
                    time.sleep(self.retry_delay)
        
        logger.warning(f"获取锁失败: {self.key}")
        return False
    
    def release(self) -> bool:
        """
        释放锁
        
        使用 Lua 脚本确保只释放自己持有的锁
        
        Returns:
            bool: 是否成功释放锁
        """
        # Lua 脚本：只有锁的持有者才能释放
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            result = self.redis.eval(lua_script, 1, self.key, self._lock_id)
            if result:
                logger.debug(f"释放锁成功: {self.key} (id={self._lock_id[:8]})")
                return True
            else:
                logger.warning(f"释放锁失败（非持有者或已过期）: {self.key}")
                return False
        except Exception as e:
            logger.error(f"释放锁异常: {self.key}, error={e}")
            return False
    
    def extend(self, additional_time: int = None) -> bool:
        """
        延长锁的过期时间
        
        Args:
            additional_time: 额外时间（秒），默认使用初始 TTL
            
        Returns:
            bool: 是否成功延长
        """
        ttl = additional_time or self.ttl
        
        # Lua 脚本：只有锁的持有者才能延长
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            result = self.redis.eval(lua_script, 1, self.key, self._lock_id, ttl)
            if result:
                logger.debug(f"延长锁成功: {self.key}, ttl={ttl}s")
                return True
            else:
                logger.warning(f"延长锁失败（非持有者或已过期）: {self.key}")
                return False
        except Exception as e:
            logger.error(f"延长锁异常: {self.key}, error={e}")
            return False
    
    def is_locked(self) -> bool:
        """检查锁是否被持有"""
        try:
            return self.redis.exists(self.key) > 0
        except Exception as e:
            logger.error(f"检查锁状态异常: {self.key}, error={e}")
            return False
    
    def __enter__(self):
        """上下文管理器入口"""
        if not self.acquire():
            raise LockAcquisitionError(f"无法获取锁: {self.key}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()
        return False


class AsyncDistributedLock(DistributedLock):
    """异步分布式锁"""
    
    async def acquire_async(self, blocking: bool = True) -> bool:
        """异步获取锁"""
        import asyncio
        
        for attempt in range(self.retry_times if blocking else 1):
            try:
                result = self.redis.set(
                    self.key,
                    self._lock_id,
                    nx=True,
                    ex=self.ttl,
                )
                if result:
                    logger.debug(f"获取锁成功: {self.key} (id={self._lock_id[:8]})")
                    return True
                
                if blocking and attempt < self.retry_times - 1:
                    logger.debug(f"获取锁失败，重试中: {self.key} (attempt={attempt + 1})")
                    await asyncio.sleep(self.retry_delay)
                    
            except Exception as e:
                logger.error(f"获取锁异常: {self.key}, error={e}")
                if blocking and attempt < self.retry_times - 1:
                    await asyncio.sleep(self.retry_delay)
        
        logger.warning(f"获取锁失败: {self.key}")
        return False
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        if not await self.acquire_async():
            raise LockAcquisitionError(f"无法获取锁: {self.key}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        self.release()
        return False


# ============ 便捷函数 ============

def agent_decision_lock(agent_id: str) -> AsyncDistributedLock:
    """获取 Agent 决策锁"""
    return AsyncDistributedLock(
        key=f"{LockKeys.AGENT_DECISION}{agent_id}",
        ttl=LockTTL.AGENT_DECISION,
        retry_times=1,  # 决策锁不重试，直接返回失败
        retry_delay=0,
    )


def agent_position_lock(agent_id: str) -> AsyncDistributedLock:
    """获取 Agent 持仓锁"""
    return AsyncDistributedLock(
        key=f"{LockKeys.AGENT_POSITION}{agent_id}",
        ttl=LockTTL.AGENT_POSITION,
        retry_times=5,
        retry_delay=0.2,
    )


def agent_balance_lock(agent_id: str) -> AsyncDistributedLock:
    """获取 Agent 余额锁"""
    return AsyncDistributedLock(
        key=f"{LockKeys.AGENT_BALANCE}{agent_id}",
        ttl=LockTTL.AGENT_BALANCE,
        retry_times=5,
        retry_delay=0.2,
    )


def agent_global_lock(agent_id: str) -> AsyncDistributedLock:
    """获取 Agent 全局锁（用于决策流程）"""
    return AsyncDistributedLock(
        key=f"{LockKeys.AGENT_GLOBAL}{agent_id}",
        ttl=LockTTL.AGENT_GLOBAL,
        retry_times=1,  # 全局锁不重试
        retry_delay=0,
    )


@asynccontextmanager
async def with_agent_lock(agent_id: str, lock_type: str = "global"):
    """
    Agent 锁的异步上下文管理器
    
    Args:
        agent_id: Agent ID
        lock_type: 锁类型 ("decision", "position", "balance", "global")
        
    Usage:
        async with with_agent_lock(agent_id, "decision"):
            # 执行决策逻辑
            ...
    """
    lock_funcs = {
        "decision": agent_decision_lock,
        "position": agent_position_lock,
        "balance": agent_balance_lock,
        "global": agent_global_lock,
    }
    
    lock_func = lock_funcs.get(lock_type, agent_global_lock)
    lock = lock_func(agent_id)
    
    try:
        async with lock:
            yield lock
    except LockAcquisitionError:
        logger.warning(f"Agent {agent_id} 正在执行其他操作，请稍后重试")
        raise
