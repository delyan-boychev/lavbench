import { useTranslation } from 'react-i18next';
import { formatLocalizedDate } from '../../utils/formatDate';
import { Star, Download, ChevronRight } from 'lucide-react';

export default function BestSubmissionCard({
  sub,
  task,
  onView,
  onDownload,
  showPrivate,
  challenge,
}) {
  const { t } = useTranslation();
  const tz = challenge?.timezone || 'UTC';
  const timeStr = sub.created_at
    ? `${formatLocalizedDate(sub.created_at, { timeZone: tz })} (${tz.replace(/_/g, ' ')})`
    : '—';

  return (
    <div
      onClick={() => onView(sub)}
      className="flex items-center justify-between p-3 rounded-lg bg-slate-900/40 border border-slate-800 hover:bg-slate-800/60 hover:border-indigo-500/40 transition-all cursor-pointer text-left w-full"
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onView(sub);
      }}
    >
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <div className="flex flex-col gap-0.5 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-bold text-slate-200 truncate">{task.title}</span>
            {sub.is_final_selection && (
              <span className="flex items-center gap-0.5 text-[10px] font-bold text-indigo-400">
                <Star className="w-3 h-3" />
                {t('submissions.final_selection_label')}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-400 flex-wrap">
            <span className="font-mono">#{sub.id}</span>
            <span>{timeStr}</span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {sub.public_score != null && (
          <div className="text-right">
            <div className="text-[9px] text-slate-500 uppercase tracking-wider">
              {t('submissions.public_score')}
            </div>
            <div className="font-mono text-xs font-bold text-indigo-400">
              {Number(sub.public_score).toFixed(4)}
            </div>
          </div>
        )}
        {showPrivate && sub.private_score != null && (
          <div className="text-right">
            <div className="text-[9px] text-slate-500 uppercase tracking-wider">
              {t('submissions.private_score')}
            </div>
            <div className="font-mono text-xs font-bold text-emerald-400">
              {Number(sub.private_score).toFixed(4)}
            </div>
          </div>
        )}
        {onDownload && (
          <span
            onClick={(e) => {
              e.stopPropagation();
              onDownload(sub);
            }}
            className="p-1.5 rounded text-slate-500 hover:text-indigo-400 hover:bg-slate-800 transition-colors cursor-pointer"
            title={t('submissions.download')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation();
                onDownload(sub);
              }
            }}
          >
            <Download size={14} />
          </span>
        )}
        <ChevronRight size={14} className="text-slate-500" />
      </div>
    </div>
  );
}
