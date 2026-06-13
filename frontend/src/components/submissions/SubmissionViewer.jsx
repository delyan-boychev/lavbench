import React from 'react';
import Badge from '../ui/Badge';
import CodeHighlight from '../ui/CodeHighlight';
import EmptyState from '../ui/EmptyState';
import ToggleField from '../ui/ToggleField';

export default function SubmissionViewer({ 
  submission, 
  currentUser, 
  onSelectFinal,
  selectingFinal = false,
  isSelectionDisabled = false,
  isSubmissionAfterDeadline = false
}) {
  if (!submission) {
    return (
      <EmptyState
        minHeight={300}
        message="Select a submission to view details."
        icon={
          <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" className="text-slate-500">
            <path strokeLinecap="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
        }
      />
    );
  }

  let cells = [];
  try {
    cells = typeof submission.code_cells === 'string'
      ? JSON.parse(submission.code_cells)
      : (submission.code_cells || []);
  } catch { 
    cells = []; 
  }

  const isCompetitor = currentUser?.role === 'competitor';
  const isAdminOrJury = currentUser?.role === 'admin' || currentUser?.role === 'jury';
  const showUserDemographics = isAdminOrJury && submission.user && (submission.user.name || submission.user.username);

  return (
    <div className="flex flex-col gap-4">
      
      {/* Main Details Card */}
      <div className="surface p-5">
        <div className="flex flex-wrap justify-between gap-3 mb-3.5">
          <div>
            <div className="flex items-center gap-2.5 mb-1">
              <span className="font-mono text-xs text-slate-500">
                Submission #{submission.id}
              </span>
              <Badge status={submission.status} />
              {submission.detailed_status && submission.detailed_status !== submission.status && (
                <Badge status={submission.detailed_status} />
              )}
              {submission.is_final_selection && (
                <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-400">
                  ★ FINAL SELECTION
                </span>
              )}
            </div>
            
            {submission.user?.alias_id && (
              <span className="text-[11px] text-slate-400 font-mono">
                Alias: {submission.user?.alias_id}
              </span>
            )}
          </div>
          <div className="flex gap-4 items-start">
            {submission.public_score != null && (
              <div className="text-right">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Public Score</div>
                <div className="font-mono text-base font-bold text-indigo-400">
                  {Number(submission.public_score).toFixed(4)}
                </div>
              </div>
            )}
            {submission.private_score != null && (
              <div className="text-right">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Private Score</div>
                <div className="font-mono text-base font-bold text-emerald-400">
                  {Number(submission.private_score).toFixed(4)}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Final Selection Selector for Competitor */}
        {isCompetitor && submission.status === 'completed' && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-850 rounded-lg">
            <ToggleField
              id={`final-check-${submission.id}`}
              checked={submission.is_final_selection}
              disabled={selectingFinal || submission.is_final_selection || isSelectionDisabled}
              onChange={() => onSelectFinal && onSelectFinal(submission.id)}
              label={submission.is_final_selection ? "This is your selected final submission for this task." : "Select as final submission (enforces anti-overfitting rules)."}
            />
            {isSelectionDisabled && !submission.is_final_selection && (
              <p className="text-[10px] text-rose-400 mt-1.5 font-semibold">
                {isSubmissionAfterDeadline 
                  ? "Cannot select a submission created after the stage deadline." 
                  : "The final selection window for this stage has closed."
                }
              </p>
            )}
          </div>
        )}

        {/* Demographics View for Jury/Admin */}
        {showUserDemographics && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-850 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              Competitor Demographics (Jury Unblinded View)
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
              <div><strong>Name:</strong> {submission.user.name} {submission.user.surname}</div>
              <div><strong>Username:</strong> {submission.user.username}</div>
              {submission.user.grade && <div><strong>Grade:</strong> {submission.user.grade}</div>}
              {submission.user.school && <div><strong>School:</strong> {submission.user.school}</div>}
              {submission.user.city && <div><strong>City:</strong> {submission.user.city}</div>}
            </div>
          </div>
        )}

        {/* Integrity View for Jury/Admin */}
        {isAdminOrJury && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-850 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              Integrity & Execution Audit
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
              <div><strong>Celery Task ID:</strong> <span className="font-mono text-[11px] text-slate-400">{submission.celery_task_id || "None"}</span></div>
              <div><strong>Execution Time:</strong> {submission.execution_time_ms ? `${submission.execution_time_ms} ms` : "—"}</div>
            </div>
          </div>
        )}

        {/* Execution Log */}
        {submission.logs && (
          <div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              Execution Log
            </div>
            <pre className={`code-panel max-h-[180px] text-xs ${submission.status === 'failed' ? 'text-rose-400' : 'text-slate-200'}`}>
              {submission.logs}
            </pre>
          </div>
        )}
      </div>

      {/* Submitted Code Cells */}
      {cells.length > 0 && (
        <div className="surface p-5">
          <div className="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-3">
            Submitted Code ({cells.length} cell{cells.length !== 1 ? 's' : ''})
          </div>
          <div className="flex flex-col gap-3">
            {cells.map((cell, idx) => (
              <div key={idx}>
                <div className="text-[10px] text-slate-500 font-mono mb-1">
                  Cell [{cell.id ?? idx}] — {cell.type || 'code'}
                </div>
                <CodeHighlight 
                  code={cell.source || ''} 
                  language={cell.type === 'code' ? 'python' : 'markdown'} 
                  wrap={true} 
                  maxHeight="200px" 
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

