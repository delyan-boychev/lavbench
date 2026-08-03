import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import SelectField from '../ui/SelectField';
import { useApp } from '../../context/AppContext';
import { useAuditLogsQuery } from '../../hooks/useAuditLogsQuery';
import { formatDateTime } from '../../utils/formatDate';

export default function AuditLogViewer() {
  const { t } = useTranslation();
  const { selectedChallenge } = useApp();
  const [selectedAction, setSelectedAction] = useState('');
  const [page, setPage] = useState(1);
  const [expandedLog, setExpandedLog] = useState(null);

  const challengeId = selectedChallenge?.id;
  const { data, isLoading } = useAuditLogsQuery(challengeId, page, selectedAction);

  const logs = data?.logs || [];
  const totalPages = data?.pages || 1;
  const totalItems = data?.total || 0;

  const handleActionChange = (val) => {
    setSelectedAction(val);
    setPage(1);
  };

  const formatDate = (iso) => formatDateTime(iso, selectedChallenge?.timezone || 'UTC');

  const getActionBadge = (action) => {
    const base = 'px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ';
    switch (action) {
      case 'create':
        return base + 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
      case 'update':
        return base + 'bg-amber-500/10 text-amber-400 border border-amber-500/20';
      case 'delete':
        return base + 'bg-rose-500/10 text-rose-400 border border-rose-500/20';
      case 'finalize':
        return base + 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20';
      case 'archive':
        return base + 'bg-slate-500/10 text-slate-400 border border-slate-500/20';
      default:
        return base + 'bg-slate-500/10 text-slate-300 border border-white/10';
    }
  };

  return (
    <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6 border-b border-white/5 pb-4">
        <div>
          <h2 className="text-xl font-bold text-white">{t('admin.audit_logs') || 'Audit Logs'}</h2>
          <p className="text-xs text-slate-400 mt-1">
            {totalItems} {t('admin.total_actions_logged') || 'total administrative actions logged'}
          </p>
        </div>

        {/* Filter Controls */}
        <div className="flex flex-wrap gap-3 w-full md:w-auto md:min-w-[200px]">
          {/* Action Filter */}
          <div className="w-full md:w-48">
            <SelectField
              value={selectedAction}
              onChange={handleActionChange}
              options={[
                { value: '', label: t('admin.all_actions') || 'All Actions' },
                { value: 'create', label: t('admin.actions.create') || 'Create' },
                { value: 'update', label: t('admin.actions.update') || 'Update' },
                { value: 'delete', label: t('admin.actions.delete') || 'Delete' },
                { value: 'finalize', label: t('admin.actions.finalize') || 'Finalize' },
                { value: 'archive', label: t('admin.actions.archive') || 'Archive' },
                {
                  value: 'reset_password',
                  label: t('admin.actions.reset_password') || 'Reset Password',
                },
              ]}
            />
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-slate-500 text-sm">{t('common.loading')}</div>
      ) : logs.length === 0 ? (
        <div className="text-center py-12 text-slate-500 text-sm">
          {t('admin.no_audit_logs') || 'No audit logs found matching criteria.'}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead>
                <tr className="border-b border-white/5 text-slate-400 font-bold uppercase tracking-wider">
                  <th className="py-3 px-4">{t('admin.timestamp') || 'Timestamp'}</th>
                  <th className="py-3 px-4">{t('admin.admin') || 'Administrator'}</th>
                  <th className="py-3 px-4">{t('admin.action') || 'Action'}</th>
                  <th className="py-3 px-4">{t('admin.target') || 'Target'}</th>
                  <th className="py-3 px-4">{t('admin.ip_address') || 'IP Address'}</th>
                  <th className="py-3 px-4 text-right">{t('admin.details') || 'Details'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {logs.map((log) => (
                  <React.Fragment key={log.id}>
                    <tr className="hover:bg-slate-900/20 transition-colors">
                      <td className="py-3.5 px-4 font-mono text-[11px] text-slate-400">
                        {formatDate(log.timestamp)}
                      </td>
                      <td className="py-3.5 px-4 font-medium text-slate-200">
                        {log.admin_username || 'System'}
                        <span className="block text-[10px] text-slate-500 font-mono mt-0.5">
                          {log.admin_id}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        <span className={getActionBadge(log.action_type)}>
                          {t(`admin.actions.${log.action_type}`) || log.action_type}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        <span className="font-semibold text-slate-300 capitalize">
                          {log.target_type}
                        </span>
                        {log.target_id && (
                          <span className="block text-[10px] text-slate-500 font-mono mt-0.5">
                            {log.target_id}
                          </span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 font-mono text-[11px] text-slate-400">
                        {log.ip_address}
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setExpandedLog(expandedLog === log.id ? null : log.id)}
                        >
                          {expandedLog === log.id
                            ? t('admin.hide') || 'Hide'
                            : t('admin.view') || 'View'}
                        </Button>
                      </td>
                    </tr>
                    {expandedLog === log.id && (
                      <tr>
                        <td
                          colSpan={6}
                          className="bg-slate-950/40 p-4 border-l border-r border-white/5"
                        >
                          <div className="bg-slate-950/80 p-4 rounded-xl border border-white/5">
                            <h4 className="text-[10px] font-bold uppercase text-slate-500 tracking-wider mb-2">
                              {t('admin.audit_details') || 'Action Payload / Meta-details'}
                            </h4>
                            <pre className="text-[11px] font-mono text-emerald-400 overflow-x-auto whitespace-pre-wrap">
                              {JSON.stringify(log.details || {}, null, 2)}
                            </pre>
                            {log.reason && (
                              <div className="mt-3 pt-3 border-t border-white/5">
                                <span className="block text-[10px] font-bold uppercase text-slate-500 tracking-wider mb-1">
                                  {t('admin.justification_reason') || 'Justification/Reason'}
                                </span>
                                <p className="text-slate-300 italic text-xs">{log.reason}</p>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex justify-between items-center mt-4 pt-4 border-t border-white/5">
              <span className="text-xs text-slate-500">
                {t('admin.page_of', { current: page, total: totalPages }) ||
                  `Page ${page} of ${totalPages}`}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  {t('common.previous') || 'Previous'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                >
                  {t('common.next') || 'Next'}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
