import React from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';

export default function WorkersStats({
  workerStats,
  workerStatsLoading,
  workerStatsError,
  fetchWorkerStats,
  formatUptime,
}) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-6 animate-fadein">
      {/* Header / Control Bar */}
      <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-white mb-1">
            {t('admin.workers.system_resources')}
          </h2>
          <p className="text-slate-400 text-xs">{t('admin.workers.monitoring_desc')}</p>
        </div>
        <div className="flex items-center gap-3">
          {workerStatsLoading && (
            <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
          )}
          <Button
            variant="secondary"
            onClick={fetchWorkerStats}
            disabled={workerStatsLoading}
            className="text-xs"
          >
            {workerStatsLoading ? t('admin.workers.refreshing') : t('admin.workers.refresh_now')}
          </Button>
        </div>
      </div>

      {/* Error Message */}
      {workerStatsError && (
        <div className="bg-rose-500/10 border border-rose-500/20 p-4 rounded-xl text-rose-400 text-xs font-semibold">
          {t('admin.workers.error_retrieving_stats', { error: workerStatsError })}
        </div>
      )}

      {/* Host Server Resources */}
      {workerStats?.system && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* CPU Card */}
          <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
            <div>
              <h3 className="text-slate-400 font-bold text-xs uppercase tracking-wider mb-2">
                {t('admin.workers.cpu_utilization')}
              </h3>
              <div className="flex items-baseline gap-2 mb-3">
                <span className="text-2xl font-extrabold text-white">
                  {workerStats.system.load_avg?.[0]?.toFixed(2) || '0.00'}
                </span>
                <span className="text-slate-500 text-[10px]">
                  {t('admin.workers.one_min_load')}
                </span>
              </div>
            </div>
            <div>
              <div className="flex justify-between text-[10px] text-slate-500 font-bold mb-1">
                <span>{t('admin.workers.load_trend')}</span>
                <span>{t('admin.workers.cores', { count: workerStats.system.cpu_count })}</span>
              </div>
              <div className="flex gap-2 font-mono text-[10px] text-indigo-400 font-semibold bg-indigo-500/5 px-3 py-1.5 rounded-lg border border-indigo-500/10">
                <span>
                  {t('admin.workers.load_5m', {
                    value: workerStats.system.load_avg?.[1]?.toFixed(2) || '0.00',
                  })}
                </span>
                <span className="text-slate-700">|</span>
                <span>
                  {t('admin.workers.load_15m', {
                    value: workerStats.system.load_avg?.[2]?.toFixed(2) || '0.00',
                  })}
                </span>
              </div>
            </div>
          </div>

          {/* RAM Memory Card */}
          <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
            <div>
              <h3 className="text-slate-400 font-bold text-xs uppercase tracking-wider mb-2">
                {t('admin.workers.memory_usage')}
              </h3>
              <div className="flex items-baseline gap-2 mb-3">
                <span className="text-2xl font-extrabold text-white">
                  {workerStats.system.memory?.percent_used || '0'}%
                </span>
                <span className="text-slate-500 text-[10px]">
                  {t('admin.workers.memory_used_total', {
                    used: workerStats.system.memory?.used_gb || '0',
                    total: workerStats.system.memory?.total_gb || '0',
                  })}
                </span>
              </div>
            </div>
            <div>
              <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden mb-2">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    (workerStats.system.memory?.percent_used || 0) > 90
                      ? 'bg-rose-500'
                      : (workerStats.system.memory?.percent_used || 0) > 75
                        ? 'bg-amber-500'
                        : 'bg-indigo-500'
                  }`}
                  style={{
                    width: `${Math.min(workerStats.system.memory?.percent_used || 0, 100)}%`,
                  }}
                ></div>
              </div>
              <div className="flex justify-between text-[10px] text-slate-500 font-bold">
                <span>
                  {t('admin.workers.used', { count: workerStats.system.memory?.used_gb || '0' })}
                </span>
                <span>
                  {t('admin.workers.free', { count: workerStats.system.memory?.free_gb || '0' })}
                </span>
              </div>
            </div>
          </div>

          {/* Disk Space Card */}
          <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
            <div>
              <h3 className="text-slate-400 font-bold text-xs uppercase tracking-wider mb-2">
                {t('admin.workers.disk_capacity')}
              </h3>
              <div className="flex items-baseline gap-2 mb-3">
                <span className="text-2xl font-extrabold text-white">
                  {workerStats.system.disk?.percent_used || '0'}%
                </span>
                <span className="text-slate-500 text-[10px]">
                  {t('admin.workers.memory_used_total', {
                    used: workerStats.system.disk?.used_gb || '0',
                    total: workerStats.system.disk?.total_gb || '0',
                  })}
                </span>
              </div>
            </div>
            <div>
              <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden mb-2">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(workerStats.system.disk?.percent_used || 0, 100)}%` }}
                ></div>
              </div>
              <div className="flex justify-between text-[10px] text-slate-500 font-bold">
                <span>
                  {t('admin.workers.used', { count: workerStats.system.disk?.used_gb || '0' })}
                </span>
                <span>
                  {t('admin.workers.free', { count: workerStats.system.disk?.free_gb || '0' })}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Workers Summary Row */}
      {workerStats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
            <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">
              {t('admin.workers.connected_workers_label')}
            </div>
            <div className="text-xl font-extrabold text-white mt-1">
              {workerStats.connected_workers_count}
            </div>
          </div>
          <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
            <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">
              {t('admin.workers.total_active_tasks')}
            </div>
            <div className="text-xl font-extrabold text-indigo-400 mt-1">
              {workerStats.workers?.reduce((sum, w) => sum + (w.active_tasks_count || 0), 0) || 0}
            </div>
          </div>
          <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
            <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">
              {t('admin.workers.reserved_tasks_label')}
            </div>
            <div className="text-xl font-extrabold text-amber-400 mt-1">
              {workerStats.workers?.reduce((sum, w) => sum + (w.reserved_tasks_count || 0), 0) || 0}
            </div>
          </div>
          <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
            <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">
              {t('admin.workers.tasks_processed_label')}
            </div>
            <div className="text-xl font-extrabold text-emerald-400 mt-1">
              {workerStats.workers?.reduce((sum, w) => sum + (w.total_tasks_processed || 0), 0) ||
                0}
            </div>
          </div>
        </div>
      )}

      {/* System Info Footnote */}
      {workerStats?.system && (
        <div className="bg-slate-900/20 border border-white/5 px-4 py-2.5 rounded-xl flex flex-wrap gap-x-6 gap-y-2 text-[10px] text-slate-500 font-mono">
          <span>
            <strong>{t('admin.workers.os')}</strong> {workerStats.system.os}{' '}
            {workerStats.system.platform_release}
          </span>
          <span>
            <strong>{t('admin.workers.python')}</strong> {workerStats.system.python_version}
          </span>
        </div>
      )}

      {/* Workers Detailed List */}
      <div className="flex flex-col gap-4">
        <h3 className="text-sm font-bold text-white uppercase tracking-wider px-1">
          {t('admin.workers.connected_nodes_label')}
        </h3>

        {!workerStats || workerStats.workers?.length === 0 ? (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl text-center text-slate-500 text-xs italic">
            {workerStatsLoading
              ? t('admin.workers.fetching_metrics')
              : t('admin.workers.no_active_workers_connected')}
          </div>
        ) : (
          workerStats.workers.map((worker) => {
            const isEvaluationWorker = worker.registered_tasks?.includes(
              'tasks.evaluate_submission',
            );
            return (
              <div
                key={worker.name}
                className="bg-[#0d0e18] border border-white/5 rounded-2xl overflow-hidden"
              >
                {/* Worker Header */}
                <div className="bg-slate-900/40 border-b border-white/5 p-5 flex flex-wrap justify-between items-center gap-4">
                  <div className="flex items-center gap-3">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                    <h4 className="font-mono text-sm font-bold text-slate-200">{worker.name}</h4>
                  </div>
                  <div className="flex items-center gap-4 text-xs font-mono">
                    <div className="text-slate-500">
                      {t('admin.workers.pid_label')}{' '}
                      <span className="text-slate-300 font-bold">{worker.pid || 'N/A'}</span>
                    </div>
                    <div className="text-slate-500">
                      {t('admin.workers.uptime_label', { time: '' })}
                      <span className="text-indigo-400 font-bold">
                        {formatUptime(worker.uptime)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Worker Stats Body */}
                <div className="p-6 grid grid-cols-1 xl:grid-cols-3 gap-6">
                  {/* Left: General Stats & Resource Usage */}
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-1 gap-6">
                    <div className="flex flex-col gap-4">
                      <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        {t('admin.workers.capacity_resource_usage')}
                      </h5>
                      <div className="bg-slate-900/20 border border-white/5 p-4 rounded-xl flex flex-col gap-3 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-500">
                            {t('admin.workers.concurrency_pool')}
                          </span>
                          <span className="font-bold text-slate-300">
                            {t('admin.workers.concurrency_pool_processes', {
                              count: worker.pool_size,
                            })}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">
                            {t('admin.workers.processed_tasks')}
                          </span>
                          <span className="font-bold text-emerald-400">
                            {worker.total_tasks_processed}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">{t('admin.workers.max_ram_usage')}</span>
                          <span className="font-bold text-slate-300">
                            {worker.rusage?.maxrss_mb ? `${worker.rusage.maxrss_mb} MB` : 'N/A'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">{t('admin.workers.cpu_time')}</span>
                          <span className="font-mono font-bold text-slate-300">
                            {worker.rusage?.utime_sec !== undefined
                              ? `${worker.rusage.utime_sec.toFixed(2)}s`
                              : 'N/A'}
                            {' / '}
                            {worker.rusage?.stime_sec !== undefined
                              ? `${worker.rusage.stime_sec.toFixed(2)}s`
                              : 'N/A'}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Broker Details */}
                    <div className="flex flex-col gap-4">
                      <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        {t('admin.workers.broker_connection')}
                      </h5>
                      <div className="bg-slate-900/20 border border-white/5 p-4 rounded-xl flex flex-col gap-2 font-mono text-[11px] text-slate-400">
                        <div>
                          <span className="text-slate-600">{t('admin.workers.transport')}</span>{' '}
                          {worker.broker?.transport || 'N/A'}
                        </div>
                        <div>
                          <span className="text-slate-600">{t('admin.workers.hostname')}</span>{' '}
                          {worker.broker?.hostname || 'N/A'}
                        </div>
                        <div>
                          <span className="text-slate-600">{t('admin.workers.port')}</span>{' '}
                          {worker.broker?.port || 'N/A'}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Middle: Active & Reserved Tasks */}
                  <div className="xl:col-span-2 flex flex-col gap-4">
                    {isEvaluationWorker ? (
                      <>
                        {/* Active Tasks */}
                        <div>
                          <div className="flex justify-between items-center mb-2">
                            <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                              {t('admin.workers.active_tasks', {
                                count: worker.active_tasks_count,
                              })}
                            </h5>
                            {worker.active_tasks_count > 0 && (
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 uppercase border border-indigo-500/20 animate-pulse">
                                {t('admin.workers.running')}
                              </span>
                            )}
                          </div>

                          {worker.active_tasks?.length === 0 ? (
                            <div className="bg-slate-900/10 border border-white/5 p-4 rounded-xl text-center text-slate-500 text-xs italic">
                              {t('admin.workers.no_active_tasks')}
                            </div>
                          ) : (
                            <div className="bg-slate-900/20 border border-white/5 rounded-xl overflow-hidden">
                              <table className="w-full text-left border-collapse text-[10px]">
                                <thead>
                                  <tr className="bg-slate-900/50 text-slate-400 font-bold uppercase border-b border-white/5">
                                    <th className="p-3">{t('admin.workers.task_id_header')}</th>
                                    <th className="p-3">{t('admin.workers.task_name_header')}</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {worker.active_tasks?.map((task) => (
                                    <tr
                                      key={task.id}
                                      className="border-b border-white/5 last:border-0 hover:bg-white/5"
                                    >
                                      <td className="p-3 font-mono text-slate-300 font-semibold">
                                        {task.id}
                                      </td>
                                      <td className="p-3 font-mono text-indigo-400">{task.name}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>

                        {/* Reserved Queue Tasks */}
                        <div className="mt-2">
                          <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">
                            {t('admin.workers.reserved_queue', {
                              count: worker.reserved_tasks_count,
                            })}
                          </h5>

                          {worker.reserved_tasks?.length === 0 ? (
                            <div className="bg-slate-900/10 border border-white/5 p-4 rounded-xl text-center text-slate-500 text-xs italic">
                              {t('admin.workers.queue_empty')}
                            </div>
                          ) : (
                            <div className="bg-slate-900/20 border border-white/5 rounded-xl overflow-hidden">
                              <table className="w-full text-left border-collapse text-[10px]">
                                <thead>
                                  <tr className="bg-slate-900/50 text-slate-400 font-bold uppercase border-b border-white/5">
                                    <th className="p-3">{t('admin.workers.task_id_header')}</th>
                                    <th className="p-3">{t('admin.workers.task_name_header')}</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {worker.reserved_tasks?.map((task) => (
                                    <tr
                                      key={task.id}
                                      className="border-b border-white/5 last:border-0 hover:bg-white/5"
                                    >
                                      <td className="p-3 font-mono text-slate-300 font-semibold">
                                        {task.id}
                                      </td>
                                      <td className="p-3 font-mono text-amber-400">{task.name}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      </>
                    ) : (
                      <div className="bg-slate-900/20 border border-white/5 p-6 rounded-2xl text-center text-slate-500 text-xs italic flex flex-col items-center justify-center gap-2">
                        <span className="text-amber-500/90 font-bold uppercase text-xs tracking-widest bg-amber-500/10 px-4 py-1.5 rounded-full border border-amber-500/20 shadow-lg shadow-amber-500/5">
                          {t('admin.workers.internal_tasks_label')}
                        </span>
                        <span>{t('admin.workers.internal_only_notice')}</span>
                      </div>
                    )}

                    {/* Registered Capabilities */}
                    <div className="mt-2">
                      <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">
                        {t('admin.workers.registered_capabilities')}
                      </h5>
                      <div className="flex flex-wrap gap-2">
                        {worker.registered_tasks?.length === 0 ? (
                          <span className="text-[10px] text-slate-500 italic">
                            {t('admin.workers.no_capabilities')}
                          </span>
                        ) : (
                          worker.registered_tasks?.map((taskName) => (
                            <span
                              key={taskName}
                              className="font-mono text-[9px] font-bold px-2 py-1 rounded bg-slate-900/60 text-slate-400 border border-white/5"
                            >
                              {taskName}
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
