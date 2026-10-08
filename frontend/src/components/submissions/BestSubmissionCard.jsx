import { useTranslation } from 'react-i18next';
import { formatLocalizedDate } from '../../utils/formatDate';
import { Star, Download, ChevronRight } from 'lucide-react';
import { formatScore } from '../../utils/formatScore';

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
    // The row is two sibling buttons (view, download) so no control is nested in another
    <div className="flex items-center gap-2 p-3 rounded-lg bg-slate-900/40 border border-slate-800 hover:bg-slate-800/60 hover:border-indigo-500/40 transition-all w-full">
      <button
        type="button"
        onClick={() => onView(sub)}
        className="flex items-center justify-between gap-3 min-w-0 flex-1 text-left cursor-pointer"
      >
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
        <div className="flex items-center gap-3 flex-shrink-0">
          {sub.public_score != null && (
            <div className="text-right">
              <div className="text-[9px] text-slate-500 uppercase tracking-wider">
                {t('submissions.public_score')}
              </div>
              <div className="font-mono text-xs font-bold text-indigo-400">
                {formatScore(sub.public_score)}
              </div>
            </div>
          )}
          {showPrivate && sub.private_score != null && (
            <div className="text-right">
              <div className="text-[9px] text-slate-500 uppercase tracking-wider">
                {t('submissions.private_score')}
              </div>
              <div className="font-mono text-xs font-bold text-emerald-400">
                {formatScore(sub.private_score)}
              </div>
            </div>
          )}
        </div>
      </button>
      <div className="flex items-center gap-1 flex-shrink-0">
        {onDownload && (
          <button
            type="button"
            onClick={() => onDownload(sub)}
            className="inline-flex items-center justify-center min-h-8 min-w-8 rounded text-slate-500 hover:text-indigo-400 hover:bg-slate-800 transition-colors cursor-pointer"
            title={t('submissions.download')}
            aria-label={t('submissions.download')}
          >
            <Download size={14} />
          </button>
        )}
        <ChevronRight size={14} className="text-slate-500" aria-hidden="true" />
      </div>
    </div>
  );
}
