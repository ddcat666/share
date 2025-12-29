import React, { useState } from 'react';
import { GlassCard } from '../ui';
import type { SystemTask, ModelAgent, TaskType } from '../../types';

interface TaskListProps {
  tasks: SystemTask[];
  agents: ModelAgent[];
  onPause: (taskId: string) => void;
  onResume: (taskId: string) => void;
  onDelete: (taskId: string) => void;
  onViewLogs: (taskId: string) => void;
  onTrigger: (taskId: string) => Promise<void>;
  onEditTask?: (taskId: string) => void;
  onAddTask?: () => void;
  loading?: boolean;
  isAuthenticated?: boolean;
  triggeringTaskId?: string | null;
}

// 任务类型显示名称
const TASK_TYPE_LABELS: Record<TaskType, string> = {
  agent_decision: 'Agent决策',
  quote_sync: '行情同步',
  market_refresh: '市场刷新',
};

/**
 * 系统任务列表组件
 * - 使用GlassCard容器，设置 className="p-6 rounded-[7px]"
 * - 表格列标题和内容左对齐（text-left）
 * - 表头使用 text-xs font-bold uppercase tracking-wider text-gray-500 样式
 * - 表格行使用斑马纹和hover效果
 * - 显示任务名称、Cron表达式、关联Agent、状态、下次执行时间
 * - 显示运行日志统计（成功x条｜失败x条），可点击查看详情
 * - 提供暂停/恢复、删除、手动触发操作按钮
 * - 状态标签使用圆角样式（active: bg-green-100, paused: bg-yellow-100）
 */
export const TaskList: React.FC<TaskListProps> = ({
  tasks,
  agents,
  onPause,
  onResume,
  onDelete,
  onViewLogs,
  onTrigger,
  onEditTask,
  onAddTask,
  loading = false,
  isAuthenticated = false,
  triggeringTaskId = null,
}) => {
  const [filterName, setFilterName] = useState('');
  const [filterType, setFilterType] = useState<'all' | 'agent_decision' | 'quote_sync'>('all');
  const [filterStatus, setFilterStatus] = useState<'all' | 'active' | 'paused'>('all');

  // 筛选任务
  const filteredTasks = tasks.filter(task => {
    const matchName = !filterName || task.name.toLowerCase().includes(filterName.toLowerCase());
    const matchType = filterType === 'all' || task.task_type === filterType;
    const matchStatus = filterStatus === 'all' || task.status === filterStatus;
    return matchName && matchType && matchStatus;
  });
  // Get agent names by IDs
  const getAgentNames = (agentIds: string[]): string => {
    if (agentIds.length === 1 && agentIds[0] === 'all') {
      return '全部Agent';
    }
    const names = agentIds
      .map(id => agents.find(a => a.agent_id === id)?.name || id)
      .slice(0, 3);
    if (agentIds.length > 3) {
      return `${names.join(', ')} 等${agentIds.length}个`;
    }
    return names.join(', ');
  };

  // Format datetime to YYYY-MM-DD HH:MM
  const formatDateTime = (dateStr: string | null): string => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  };

  // Status badge component
  const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
    const isActive = status === 'active';
    return (
      <span
        className={`
          inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-semibold
          ${isActive ? 'bg-green-100 text-green-600' : 'bg-yellow-100 text-yellow-600'}
        `}
      >
        {isActive ? '运行中' : '已暂停'}
      </span>
    );
  };

  // Task type badge component
  const TaskTypeBadge: React.FC<{ taskType: TaskType }> = ({ taskType }) => {
    const isAgentDecision = taskType === 'agent_decision';
    return (
      <span
        className={`
          inline-flex items-center px-2 py-0.5 rounded text-xs font-medium
          ${isAgentDecision ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'}
        `}
      >
        {TASK_TYPE_LABELS[taskType] || taskType}
      </span>
    );
  };

  // Log stats component (clickable)
  const LogStats: React.FC<{ taskId: string; successCount: number; failCount: number }> = ({
    taskId,
    successCount,
    failCount,
  }) => (
    <button
      onClick={() => onViewLogs(taskId)}
      className="text-sm hover:underline focus:outline-none"
    >
      <span className="text-green-600">成功{successCount}条</span>
      <span className="text-gray-400 mx-1">|</span>
      <span className="text-red-500">失败{failCount}条</span>
    </button>
  );

  // Action buttons component
  const ActionButtons: React.FC<{ task: SystemTask }> = ({ task }) => {
    const isTriggering = triggeringTaskId === task.task_id;
    const disabled = !isAuthenticated || isTriggering;
    
    return (
      <div className="flex items-center gap-2">
        {/* Edit button */}
        {onEditTask && (
          <button
            onClick={() => onEditTask(task.task_id)}
            disabled={disabled}
            className="p-1.5 rounded-lg hover:bg-blue-50 text-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title={!isAuthenticated ? '需要登录' : '编辑'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
        )}

        {/* Pause/Resume button */}
        {task.status === 'active' ? (
          <button
            onClick={() => onPause(task.task_id)}
            disabled={disabled}
            className="p-1.5 rounded-lg hover:bg-yellow-50 text-yellow-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title={!isAuthenticated ? '需要登录' : '暂停'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
        ) : (
          <button
            onClick={() => onResume(task.task_id)}
            disabled={disabled}
            className="p-1.5 rounded-lg hover:bg-green-50 text-green-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title={!isAuthenticated ? '需要登录' : '恢复'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
        )}

        {/* Trigger button */}
        <button
          onClick={() => onTrigger(task.task_id)}
          disabled={disabled}
          className="p-1.5 rounded-lg hover:bg-blue-50 text-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title={!isAuthenticated ? '需要登录' : isTriggering ? '执行中...' : '手动触发'}
        >
          {isTriggering ? (
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          )}
        </button>

        {/* Delete button */}
        <button
          onClick={() => onDelete(task.task_id)}
          disabled={disabled}
          className="p-1.5 rounded-lg hover:bg-red-50 text-red-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title={!isAuthenticated ? '需要登录' : '删除'}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </div>
    );
  };

  return (
    <GlassCard className="p-3 rounded-[7px]">
      {/* 筛选栏 */}
      <div className="flex flex-col md:flex-row gap-2 items-end mb-3">
        <input
          type="text"
          value={filterName}
          onChange={(e) => setFilterName(e.target.value)}
          placeholder="搜索任务名称..."
          className="flex-1 px-3 py-1.5 text-sm rounded-lg bg-gray-100 border-none outline-none focus:ring-2 focus:ring-space-black/20"
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as 'all' | 'agent_decision' | 'quote_sync')}
          className="px-3 py-1.5 text-sm rounded-lg bg-gray-100 border-none outline-none focus:ring-2 focus:ring-space-black/20 cursor-pointer"
        >
          <option value="all">全部类型</option>
          <option value="agent_decision">Agent决策</option>
          <option value="quote_sync">行情同步</option>
        </select>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value as 'all' | 'active' | 'paused')}
          className="px-3 py-1.5 text-sm rounded-lg bg-gray-100 border-none outline-none focus:ring-2 focus:ring-space-black/20 cursor-pointer"
        >
          <option value="all">全部状态</option>
          <option value="active">运行中</option>
          <option value="paused">已暂停</option>
        </select>
        {onAddTask && (
          <button
            onClick={onAddTask}
            disabled={!isAuthenticated}
            className="px-4 py-1.5 text-sm font-medium text-white bg-space-black hover:bg-graphite rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title={!isAuthenticated ? '需要登录才能执行此操作' : ''}
          >
            新建
          </button>
        )}
      </div>

      {/* 任务统计 */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-500">
          共 <span className="font-semibold text-space-black">{filteredTasks.length}</span> / {tasks.length} 个任务
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200/40">
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                任务名称
              </th>
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                类型
              </th>
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                Cron表达式
              </th>
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                关联Agent
              </th>
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                状态
              </th>
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                下次执行
              </th>
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                运行日志
              </th>
              <th className="py-2 px-2 text-left text-xs font-bold uppercase tracking-wider text-gray-500">
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-gray-400 text-sm">
                  加载中...
                </td>
              </tr>
            ) : filteredTasks.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-gray-400 text-sm">
                  {tasks.length === 0 ? '暂无任务' : '没有匹配的任务'}
                </td>
              </tr>
            ) : (
              filteredTasks.map((task, index) => (
                <tr
                  key={task.task_id}
                  className={`
                    border-b border-gray-100/40
                    hover:bg-gray-50/50 transition-colors
                    ${index % 2 === 0 ? 'bg-white/20' : 'bg-gray-50/20'}
                  `}
                >
                  {/* Task Name */}
                  <td className="py-2 px-2 text-left">
                    <div className="flex flex-col">
                      <span className="font-semibold text-space-black text-sm">{task.name}</span>
                      {task.trading_day_only && (
                        <span className="text-xs text-gray-400 mt-0.5">仅交易日</span>
                      )}
                    </div>
                  </td>

                  {/* Task Type */}
                  <td className="py-2 px-2 text-left">
                    <TaskTypeBadge taskType={task.task_type || 'agent_decision'} />
                  </td>

                  {/* Cron Expression */}
                  <td className="py-2 px-2 text-left">
                    <div className="flex flex-col">
                      <code className="text-xs font-mono text-gray-700">{task.cron_expression}</code>
                      <span className="text-xs text-gray-400 mt-0.5">{task.cron_description}</span>
                    </div>
                  </td>

                  {/* Associated Agents - Only show for agent_decision type */}
                  <td className="py-2 px-2 text-left">
                    {(task.task_type || 'agent_decision') === 'agent_decision' ? (
                      <span className="text-xs text-gray-700">{getAgentNames(task.agent_ids)}</span>
                    ) : (
                      <span className="text-xs text-gray-400">-</span>
                    )}
                  </td>

                  {/* Status */}
                  <td className="py-2 px-2 text-left">
                    <StatusBadge status={task.status} />
                  </td>

                  {/* Next Run Time */}
                  <td className="py-2 px-2 text-left">
                    <span className="text-xs text-gray-600">
                      {formatDateTime(task.next_run_time)}
                    </span>
                  </td>

                  {/* Log Stats */}
                  <td className="py-2 px-2 text-left">
                    <LogStats
                      taskId={task.task_id}
                      successCount={task.success_count}
                      failCount={task.fail_count}
                    />
                  </td>

                  {/* Actions */}
                  <td className="py-2 px-2 text-left">
                    <ActionButtons task={task} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
};

export default TaskList;
