import React, { useState, useEffect, useCallback } from 'react';
import { Label } from '../ui';
import type { ModelAgent, TaskCreate, TaskType, SystemTask } from '../../types';
import { taskApi } from '../../services/api';

interface TaskFormProps {
  agents: ModelAgent[];
  task?: SystemTask;
  onSubmit: (task: TaskCreate) => Promise<void>;
  onCancel: () => void;
  loading?: boolean;
}

interface FormData {
  name: string;
  task_type: TaskType;
  cron_expression: string;
  agent_ids: string[];
  trading_day_only: boolean;
  select_all_agents: boolean;
  // Quote sync config
  quote_sync_stocks: string;
  quote_sync_days: number;
  quote_sync_force_full: boolean;
  // Market refresh config
  market_refresh_sentiment: boolean;
  market_refresh_indices: boolean;
  market_refresh_hot_stocks: boolean;
}

interface FormErrors {
  name?: string;
  cron_expression?: string;
  agent_ids?: string;
}

interface CronValidation {
  valid: boolean;
  description: string;
  error: string | null;
  next_run_time: string | null;
}

// 常用Cron表达式预设
const CRON_PRESETS = [
  { label: '每天9:30', value: '30 9 * * *', description: '每天 09:30 执行' },
  { label: '每天15:00', value: '0 15 * * *', description: '每天 15:00 执行' },
  { label: '工作日9:30', value: '30 9 * * 1-5', description: '每周一至周五 09:30 执行' },
  { label: '每小时', value: '0 * * * *', description: '每小时的第0分钟执行' },
  { label: '每30分钟', value: '*/30 * * * *', description: '每30分钟执行' },
];

// 任务类型选项
const TASK_TYPE_OPTIONS = [
  { value: 'agent_decision', label: 'Agent决策', description: '执行AI Agent的交易决策' },
  { value: 'quote_sync', label: '行情同步', description: '同步股票行情数据' },
  { value: 'market_refresh', label: '市场刷新', description: '刷新市场情绪、指数、热门股票' },
];

/**
 * 任务创建表单组件
 * - 任务名称输入框
 * - Cron表达式输入框，实时显示人性化描述
 * - Agent多选器（支持选择全部或指定Agent）
 * - "仅交易日运行"勾选框
 * - 使用项目统一的Label和PrimaryButton组件
 * - 表单验证和错误提示
 */
export const TaskForm: React.FC<TaskFormProps> = ({
  agents,
  task,
  onSubmit,
  onCancel,
  loading = false,
}) => {
  const [formData, setFormData] = useState<FormData>({
    name: task?.name || '',
    task_type: task?.task_type || 'agent_decision',
    cron_expression: task?.cron_expression || '30 9 * * *',
    agent_ids: task?.task_type === 'agent_decision' ? task?.agent_ids || [] : [],
    trading_day_only: task?.trading_day_only ?? true,
    select_all_agents: task?.task_type === 'agent_decision' ? (task?.agent_ids?.length === 1 && task?.agent_ids[0] === 'all') ?? true : true,
    // Quote sync config
    quote_sync_stocks: task?.task_type === 'quote_sync' && task?.config?.stock_codes ? (task.config.stock_codes as string[]).join(',') : '',
    quote_sync_days: task?.task_type === 'quote_sync' && task?.config?.days ? (task.config.days as number) : 7,
    quote_sync_force_full: task?.task_type === 'quote_sync' && task?.config?.force_full ? (task.config.force_full as boolean) : false,
    // Market refresh config
    market_refresh_sentiment: task?.task_type === 'market_refresh' && task?.config?.refresh_types ? (task.config.refresh_types as string[]).includes('sentiment') : true,
    market_refresh_indices: task?.task_type === 'market_refresh' && task?.config?.refresh_types ? (task.config.refresh_types as string[]).includes('indices') : true,
    market_refresh_hot_stocks: task?.task_type === 'market_refresh' && task?.config?.refresh_types ? (task.config.refresh_types as string[]).includes('hot_stocks') : true,
  });

  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [cronValidation, setCronValidation] = useState<CronValidation>({
    valid: true,
    description: '每天 09:30 执行',
    error: null,
    next_run_time: null,
  });
  const [validatingCron, setValidatingCron] = useState(false);

  // Debounced cron validation
  useEffect(() => {
    const timer = setTimeout(() => {
      if (formData.cron_expression.trim()) {
        validateCronExpression(formData.cron_expression);
      } else {
        setCronValidation({
          valid: false,
          description: '',
          error: 'Cron表达式不能为空',
          next_run_time: null,
        });
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [formData.cron_expression]);

  const validateCronExpression = useCallback(async (expression: string) => {
    setValidatingCron(true);
    try {
      const result = await taskApi.validateCron(expression);
      setCronValidation(result);
    } catch (err) {
      setCronValidation({
        valid: false,
        description: '',
        error: '验证失败，请检查表达式格式',
        next_run_time: null,
      });
    } finally {
      setValidatingCron(false);
    }
  }, []);

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};

    if (!formData.name.trim()) {
      newErrors.name = '请输入任务名称';
    } else if (formData.name.length > 100) {
      newErrors.name = '任务名称不能超过100个字符';
    }

    if (!formData.cron_expression.trim()) {
      newErrors.cron_expression = 'Cron表达式不能为空';
    } else if (!cronValidation.valid) {
      newErrors.cron_expression = cronValidation.error || 'Cron表达式格式错误';
    }

    // Only validate agent selection for agent_decision type
    if (formData.task_type === 'agent_decision') {
      if (!formData.select_all_agents && formData.agent_ids.length === 0) {
        newErrors.agent_ids = '请至少选择一个Agent';
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) return;

    setSubmitting(true);
    try {
      const taskData: TaskCreate = {
        name: formData.name.trim(),
        task_type: formData.task_type,
        cron_expression: formData.cron_expression.trim(),
        trading_day_only: formData.trading_day_only,
      };

      // Add agent_ids only for agent_decision type
      if (formData.task_type === 'agent_decision') {
        taskData.agent_ids = formData.select_all_agents ? ['all'] : formData.agent_ids;
      }

      // Add config for quote_sync type
      if (formData.task_type === 'quote_sync') {
        const stockCodes = formData.quote_sync_stocks
          .split(',')
          .map(s => s.trim())
          .filter(s => s.length > 0);
        taskData.config = {
          stock_codes: stockCodes,
          days: formData.quote_sync_days,
          force_full: formData.quote_sync_force_full,
        };
      }

      // Add config for market_refresh type
      if (formData.task_type === 'market_refresh') {
        const refreshTypes: string[] = [];
        if (formData.market_refresh_sentiment) refreshTypes.push('sentiment');
        if (formData.market_refresh_indices) refreshTypes.push('indices');
        if (formData.market_refresh_hot_stocks) refreshTypes.push('hot_stocks');
        taskData.config = {
          refresh_types: refreshTypes,
        };
      }

      await onSubmit(taskData);
    } catch (error) {
      console.error('Submit error:', error);
    } finally {
      setSubmitting(false);
    }
  };

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({ ...prev, name: e.target.value }));
    if (errors.name) {
      setErrors(prev => ({ ...prev, name: undefined }));
    }
  };

  const handleCronChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({ ...prev, cron_expression: e.target.value }));
    if (errors.cron_expression) {
      setErrors(prev => ({ ...prev, cron_expression: undefined }));
    }
  };

  const handlePresetClick = (preset: typeof CRON_PRESETS[0]) => {
    setFormData(prev => ({ ...prev, cron_expression: preset.value }));
    setCronValidation({
      valid: true,
      description: preset.description,
      error: null,
      next_run_time: null,
    });
    if (errors.cron_expression) {
      setErrors(prev => ({ ...prev, cron_expression: undefined }));
    }
  };

  const handleSelectAllChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({
      ...prev,
      select_all_agents: e.target.checked,
      agent_ids: e.target.checked ? [] : prev.agent_ids,
    }));
    if (errors.agent_ids) {
      setErrors(prev => ({ ...prev, agent_ids: undefined }));
    }
  };

  const handleAgentToggle = (agentId: string) => {
    setFormData(prev => {
      const newAgentIds = prev.agent_ids.includes(agentId)
        ? prev.agent_ids.filter(id => id !== agentId)
        : [...prev.agent_ids, agentId];
      return { ...prev, agent_ids: newAgentIds };
    });
    if (errors.agent_ids) {
      setErrors(prev => ({ ...prev, agent_ids: undefined }));
    }
  };

  const handleTradingDayChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({ ...prev, trading_day_only: e.target.checked }));
  };

  // Format next run time
  const formatNextRunTime = (isoString: string | null): string => {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Task Name */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="task-name">任务名称</Label>
        <input
          id="task-name"
          type="text"
          placeholder="输入任务名称"
          value={formData.name}
          onChange={handleNameChange}
          disabled={loading || submitting}
          className={`
            shadow-inner bg-gray-100/50 border rounded-lg px-4 py-3
            focus:ring-2 focus:ring-space-black/20 focus:outline-none
            transition-all duration-200 placeholder:text-gray-400
            disabled:opacity-50 disabled:cursor-not-allowed
            ${errors.name ? 'border-loss-red ring-1 ring-loss-red/20' : 'border-gray-200/40'}
          `}
        />
        {errors.name && <span className="text-loss-red text-xs">{errors.name}</span>}
      </div>

      {/* Task Type */}
      <div className="flex flex-col gap-1.5">
        <Label>任务类型</Label>
        <div className="flex gap-3">
          {TASK_TYPE_OPTIONS.map(option => (
            <label
              key={option.value}
              className={`
                flex-1 flex flex-col p-3 rounded-lg border cursor-pointer transition-all
                ${formData.task_type === option.value
                  ? 'border-space-black bg-space-black/5'
                  : 'border-gray-200 hover:border-gray-300'}
                ${(loading || submitting) ? 'opacity-50 cursor-not-allowed' : ''}
              `}
            >
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  name="task_type"
                  value={option.value}
                  checked={formData.task_type === option.value}
                  onChange={(e) => setFormData(prev => ({ ...prev, task_type: e.target.value as TaskType }))}
                  disabled={loading || submitting}
                  className="w-4 h-4 text-space-black focus:ring-space-black/20"
                />
                <span className="text-sm font-medium text-gray-700">{option.label}</span>
              </div>
              <span className="text-xs text-gray-400 mt-1 ml-6">{option.description}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Cron Expression */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="cron-expression">Cron表达式</Label>
        <input
          id="cron-expression"
          type="text"
          placeholder="例如: 30 9 * * * (每天9:30)"
          value={formData.cron_expression}
          onChange={handleCronChange}
          disabled={loading || submitting}
          className={`
            shadow-inner bg-gray-100/50 border rounded-lg px-4 py-3 font-mono
            focus:ring-2 focus:ring-space-black/20 focus:outline-none
            transition-all duration-200 placeholder:text-gray-400
            disabled:opacity-50 disabled:cursor-not-allowed
            ${errors.cron_expression || (!cronValidation.valid && formData.cron_expression) 
              ? 'border-loss-red ring-1 ring-loss-red/20' 
              : 'border-gray-200/40'}
          `}
        />
        
        {/* Cron validation feedback */}
        <div className="min-h-[20px]">
          {validatingCron ? (
            <span className="text-gray-400 text-xs">验证中...</span>
          ) : cronValidation.valid && formData.cron_expression ? (
            <div className="flex items-center gap-2">
              <span className="text-green-600 text-xs flex items-center gap-1">
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
                {cronValidation.description}
              </span>
              {cronValidation.next_run_time && (
                <span className="text-gray-400 text-xs">
                  (下次: {formatNextRunTime(cronValidation.next_run_time)})
                </span>
              )}
            </div>
          ) : cronValidation.error ? (
            <span className="text-loss-red text-xs">{cronValidation.error}</span>
          ) : errors.cron_expression ? (
            <span className="text-loss-red text-xs">{errors.cron_expression}</span>
          ) : null}
        </div>

        {/* Cron presets */}
        <div className="flex flex-wrap gap-2 mt-1">
          {CRON_PRESETS.map(preset => (
            <button
              key={preset.value}
              type="button"
              onClick={() => handlePresetClick(preset)}
              disabled={loading || submitting}
              className={`
                px-2.5 py-1 text-xs rounded-lg border transition-colors
                ${formData.cron_expression === preset.value
                  ? 'bg-space-black text-white border-space-black'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:bg-gray-50'}
                disabled:opacity-50 disabled:cursor-not-allowed
              `}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>

      {/* Agent Selection - Only for agent_decision type */}
      {formData.task_type === 'agent_decision' && (
        <div className="flex flex-col gap-2">
          <Label>关联Agent</Label>
          
          {/* Select All Checkbox */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={formData.select_all_agents}
              onChange={handleSelectAllChange}
              disabled={loading || submitting}
              className="w-4 h-4 rounded border-gray-300 text-space-black focus:ring-space-black/20"
            />
            <span className="text-sm text-gray-700">全部Agent</span>
          </label>

          {/* Individual Agent Selection */}
          {!formData.select_all_agents && (
            <div className="mt-2 max-h-40 overflow-y-auto border border-gray-200/40 rounded-lg p-3 bg-gray-50/50">
              {agents.length === 0 ? (
                <span className="text-gray-400 text-sm">暂无可用Agent</span>
              ) : (
                <div className="space-y-2">
                  {agents.filter(a => a.status === 'active').map(agent => (
                    <label key={agent.agent_id} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formData.agent_ids.includes(agent.agent_id)}
                        onChange={() => handleAgentToggle(agent.agent_id)}
                        disabled={loading || submitting}
                        className="w-4 h-4 rounded border-gray-300 text-space-black focus:ring-space-black/20"
                      />
                      <span className="text-sm text-gray-700">{agent.name}</span>
                      <span className="text-xs text-gray-400">({agent.llm_model})</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
          
          {errors.agent_ids && <span className="text-loss-red text-xs">{errors.agent_ids}</span>}
        </div>
      )}

      {/* Quote Sync Config - Only for quote_sync type */}
      {formData.task_type === 'quote_sync' && (
        <div className="flex flex-col gap-3 p-4 bg-gray-50/50 rounded-lg border border-gray-200/40">
          <Label>行情同步配置</Label>
          
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-gray-500">指定股票代码</label>
            <input
              type="text"
              placeholder="600519,000001（留空同步热门股票）"
              value={formData.quote_sync_stocks}
              onChange={(e) => setFormData(prev => ({ ...prev, quote_sync_stocks: e.target.value }))}
              disabled={loading || submitting}
              className="shadow-inner bg-white border border-gray-200/40 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-space-black/20 focus:outline-none"
            />
            <span className="text-xs text-gray-400">多个代码逗号分隔，留空自动同步成交额前20</span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-gray-500">同步天数</label>
              <input
                type="number"
                min="1"
                max="365"
                value={formData.quote_sync_days}
                onChange={(e) => setFormData(prev => ({ ...prev, quote_sync_days: parseInt(e.target.value) || 7 }))}
                disabled={loading || submitting}
                className="shadow-inner bg-white border border-gray-200/40 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-space-black/20 focus:outline-none"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 cursor-pointer pb-2">
                <input
                  type="checkbox"
                  checked={formData.quote_sync_force_full}
                  onChange={(e) => setFormData(prev => ({ ...prev, quote_sync_force_full: e.target.checked }))}
                  disabled={loading || submitting}
                  className="w-4 h-4 rounded border-gray-300 text-space-black focus:ring-space-black/20"
                />
                <span className="text-sm text-gray-700">强制全量同步</span>
              </label>
            </div>
          </div>
        </div>
      )}

      {/* Market Refresh Config - Only for market_refresh type */}
      {formData.task_type === 'market_refresh' && (
        <div className="flex flex-col gap-3 p-4 bg-gray-50/50 rounded-lg border border-gray-200/40">
          <Label>市场刷新配置</Label>
          <span className="text-xs text-gray-400">选择需要刷新的数据类型</span>
          
          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.market_refresh_sentiment}
                onChange={(e) => setFormData(prev => ({ ...prev, market_refresh_sentiment: e.target.checked }))}
                disabled={loading || submitting}
                className="w-4 h-4 rounded border-gray-300 text-space-black focus:ring-space-black/20"
              />
              <span className="text-sm text-gray-700">市场情绪</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.market_refresh_indices}
                onChange={(e) => setFormData(prev => ({ ...prev, market_refresh_indices: e.target.checked }))}
                disabled={loading || submitting}
                className="w-4 h-4 rounded border-gray-300 text-space-black focus:ring-space-black/20"
              />
              <span className="text-sm text-gray-700">指数概览</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.market_refresh_hot_stocks}
                onChange={(e) => setFormData(prev => ({ ...prev, market_refresh_hot_stocks: e.target.checked }))}
                disabled={loading || submitting}
                className="w-4 h-4 rounded border-gray-300 text-space-black focus:ring-space-black/20"
              />
              <span className="text-sm text-gray-700">热门股票</span>
            </label>
          </div>
        </div>
      )}

      {/* Trading Day Only */}
      <div className="flex flex-col gap-1.5">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={formData.trading_day_only}
            onChange={handleTradingDayChange}
            disabled={loading || submitting}
            className="w-4 h-4 rounded border-gray-300 text-space-black focus:ring-space-black/20"
          />
          <span className="text-sm text-gray-700">仅交易日运行</span>
        </label>
        <span className="text-xs text-gray-400 ml-6">
          勾选后，任务将在周末和法定节假日自动跳过
        </span>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-100">
        <button
          type="button"
          onClick={onCancel}
          disabled={submitting}
          className="px-4 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 hover:bg-gray-50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          取消
        </button>
        <button
          type="submit"
          disabled={loading || submitting || !cronValidation.valid}
          className="px-4 py-1.5 text-sm font-medium text-white bg-space-black hover:bg-graphite rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? '保存中...' : '保存'}
        </button>
      </div>
    </form>
  );
};

export default TaskForm;
