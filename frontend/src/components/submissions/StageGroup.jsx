import Badge from '../ui/Badge';
import BestSubmissionCard from './BestSubmissionCard';

export default function StageGroup({
  stage,
  tasks,
  challenge,
  bestSubs,
  onView,
  onDownload,
  showPrivate,
  onTaskClick,
}) {
  if (!tasks || tasks.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 px-1">
        <span className="text-[10px] font-extrabold uppercase tracking-wider text-emerald-400">
          {stage ? stage.title : challenge?.title}
        </span>
        {stage && (
          <Badge
            status={
              stage.is_finalized && stage.reveal_results
                ? 'public'
                : stage.is_finalized && !stage.reveal_results
                  ? 'internal'
                  : new Date() > new Date(stage.end_time)
                    ? 'grading'
                    : new Date() < new Date(stage.start_time)
                      ? 'future'
                      : 'active'
            }
          />
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        {tasks.map((task) => {
          const sub = bestSubs[task.id];
          if (sub) {
            return (
              <BestSubmissionCard
                key={task.id}
                sub={sub}
                task={task}
                onView={onView}
                onDownload={onDownload}
                showPrivate={showPrivate}
                challenge={challenge}
              />
            );
          }
          return (
            <button
              key={task.id}
              onClick={() => onTaskClick && onTaskClick(task.id)}
              className="flex items-center justify-between p-3 rounded-lg bg-slate-900/40 border border-slate-800 text-left w-full opacity-50 hover:opacity-80 hover:bg-slate-800/60 hover:border-slate-700 transition-all cursor-pointer"
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="flex flex-col gap-0.5 min-w-0">
                  <span className="text-sm font-bold text-slate-400 truncate">{task.title}</span>
                  <div className="flex items-center gap-3 text-xs text-slate-600">
                    <span className="font-mono">—</span>
                    <span>—</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <div className="text-right">
                  <div className="text-[9px] text-slate-600 uppercase tracking-wider">Score</div>
                  <div className="font-mono text-xs text-slate-600">—</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
