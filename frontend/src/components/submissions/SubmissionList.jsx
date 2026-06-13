import React from 'react';
import Badge from '../ui/Badge';
import Pagination from '../ui/Pagination';

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function SubmissionList({ 
  submissions, 
  selected, 
  onSelect, 
  loading,
  page,
  pages,
  total,
  perPage,
  onPageChange
}) {
  if (loading) {
    return (
      <div className="surface empty-state min-h-[200px]">
        <div className="animate-spin w-5.5 h-5.5 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
        <p>Loading submissions...</p>
      </div>
    );
  }

  if (!submissions || submissions.length === 0) {
    return (
      <div className="surface empty-state min-h-[200px]">
        <svg width="28" height="28" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" className="text-slate-500">
          <path strokeLinecap="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
        <p>No submissions found for this task.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1 px-1">
        Submissions ({total || submissions.length})
      </div>
      <div className="flex flex-col gap-1.5">
        {submissions.map(sub => {
          const isSelected = selected?.id === sub.id;
          return (
            <button
              key={sub.id}
              onClick={() => onSelect(sub)}
              className={`flex flex-col gap-1.5 p-3 rounded-lg text-left w-full transition-all duration-150 border cursor-pointer ${
                isSelected 
                  ? 'bg-indigo-500/10 border-indigo-500/40 text-slate-100' 
                  : 'bg-slate-900/40 border-slate-800 hover:bg-slate-800/60 text-slate-300'
              }`}
            >
              <div className="flex justify-between items-center gap-2 w-full">
                <span className="font-mono text-xs text-slate-500">
                  #{sub.id}
                </span>
                <Badge status={sub.status} />
              </div>

              <div className="flex justify-between items-center gap-2 w-full">
                <span className="text-xs text-slate-400">
                  {fmtTime(sub.created_at)}
                </span>
                {sub.public_score != null && (
                  <span className="font-mono text-xs font-bold text-indigo-400">
                    {Number(sub.public_score).toFixed(4)}
                  </span>
                )}
              </div>

              {sub.user?.alias_id && (
                <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                  Alias: {sub.user.alias_id}
                </div>
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-2">
        <Pagination
          page={page}
          pages={pages}
          total={total}
          perPage={perPage}
          onPageChange={onPageChange}
          itemName="submissions"
        />
      </div>
    </div>
  );
}

