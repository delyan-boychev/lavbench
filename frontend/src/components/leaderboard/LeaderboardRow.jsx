import React, { useState, useEffect } from 'react';
import { useAuth } from '../../AuthContext';
import ChallengeService from '../../services/ChallengeService';
import { useApp } from '../../context/AppContext';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Download, Pencil } from 'lucide-react';

const MEDAL_STYLES = [
  'bg-gradient-to-br from-amber-400 to-amber-600 text-amber-950 border-amber-300 shadow-[0_0_8px_rgba(251,191,36,0.3)]',
  'bg-gradient-to-br from-slate-300 to-slate-400 text-slate-800 border-slate-200 shadow-[0_0_6px_rgba(148,163,184,0.25)]',
  'bg-gradient-to-br from-amber-600 to-amber-800 text-amber-100 border-amber-500/60 shadow-[0_0_5px_rgba(180,83,9,0.2)]',
];

export default function Row({
  entry,
  rank,
  tasks,
  isCurrentUser,
  isFinalized,
  doubleBlind,
  isExpanded,
  onToggleExpand,
  challengeId,
  showPublicCols,
  showPrivateCols,
  showPointsCols,
  perTaskShowPrivateCols,
  perTaskShowPointsCols,
  activeTab,
  rowRef,
  challenge,
  onEditPoints,
}) {
  const { currentUser } = useAuth();
  const { showToast } = useApp();
  const { t } = useTranslation();
  const isAdmin = currentUser?.role === 'admin';
  const isJury = currentUser?.role === 'jury';
  const isJuryOrAdmin = isAdmin || isJury;
  const showIdentity = isAdmin || isCurrentUser || !doubleBlind || isFinalized;
  const showDemographics =
    !!entry.user && showIdentity && (!entry.user.is_anonymous || isAdmin || isCurrentUser);
  const isBaseline = entry.is_baseline_entry;
  const medalStyle = !isBaseline && rank >= 1 && rank <= 3 ? MEDAL_STYLES[rank - 1] : null;

  const isCompetitor = currentUser?.role === 'competitor';
  const challengeStages = challenge?.stages;
  const visibleStages = React.useMemo(() => {
    const now = new Date();
    if (!isCompetitor) return challengeStages || [];
    return challengeStages?.filter((st) => new Date(st.start_time) <= now) || [];
  }, [challengeStages, isCompetitor]);

  const isStageTab = visibleStages.some((st) => st.id === activeTab);
  const stageTasks = isStageTab ? tasks.filter((t) => t.stage_id === activeTab) : [];

  let displayPublic = entry.public_score;
  let displayPrivate = entry.private_score;
  let displayPoints = entry.total_points;

  if (isStageTab) {
    let hasPublic = false;
    let hasPrivate = false;
    let pubSum = 0;
    let privSum = 0;
    let ptsSum = 0;

    stageTasks.forEach((t) => {
      const scObj = entry.task_scores?.[t.id.toString()];
      if (scObj) {
        if (scObj.public_score != null) {
          pubSum += scObj.public_score;
          hasPublic = true;
        }
        if (scObj.private_score != null) {
          privSum += scObj.private_score;
          hasPrivate = true;
        }
      }
      ptsSum += entry.user?.manual_points?.[t.id.toString()] ?? 0;
    });

    displayPublic = hasPublic ? pubSum : null;
    displayPrivate = hasPrivate ? privSum : null;
    displayPoints = ptsSum;
  }

  const activeTask =
    !isStageTab && activeTab !== 'general' ? tasks.find((t) => t.id === activeTab) : null;
  const scoreObj = activeTask ? entry.task_scores?.[activeTask.id.toString()] || {} : {};

  const [flashPublic, setFlashPublic] = useState(false);
  const [flashPrivate, setFlashPrivate] = useState(false);
  const [flashPoints, setFlashPoints] = useState(false);

  const prevPublicRef = React.useRef(displayPublic);
  const prevPrivateRef = React.useRef(displayPrivate);
  const prevPointsRef = React.useRef(displayPoints);

  const prevTaskPublicRef = React.useRef(scoreObj.public_score);
  const prevTaskPrivateRef = React.useRef(scoreObj.private_score);

  useEffect(() => {
    let t1, t2, t3;
    if (activeTab === 'general' || isStageTab) {
      if (displayPublic !== prevPublicRef.current) {
        if (
          prevPublicRef.current !== undefined &&
          prevPublicRef.current !== null &&
          displayPublic !== null
        ) {
          setFlashPublic(true);
          t1 = setTimeout(() => setFlashPublic(false), 2000);
        }
        prevPublicRef.current = displayPublic;
      }
      if (displayPrivate !== prevPrivateRef.current) {
        if (
          prevPrivateRef.current !== undefined &&
          prevPrivateRef.current !== null &&
          displayPrivate !== null
        ) {
          setFlashPrivate(true);
          t2 = setTimeout(() => setFlashPrivate(false), 2000);
        }
        prevPrivateRef.current = displayPrivate;
      }
      if (displayPoints !== prevPointsRef.current) {
        if (
          prevPointsRef.current !== undefined &&
          prevPointsRef.current !== null &&
          displayPoints !== null
        ) {
          setFlashPoints(true);
          t3 = setTimeout(() => setFlashPoints(false), 2000);
        }
        prevPointsRef.current = displayPoints;
      }
    } else {
      if (scoreObj.public_score !== prevTaskPublicRef.current) {
        if (
          prevTaskPublicRef.current !== undefined &&
          prevTaskPublicRef.current !== null &&
          scoreObj.public_score !== null
        ) {
          setFlashPublic(true);
          t1 = setTimeout(() => setFlashPublic(false), 2000);
        }
        prevTaskPublicRef.current = scoreObj.public_score;
      }
      if (scoreObj.private_score !== prevTaskPrivateRef.current) {
        if (
          prevTaskPrivateRef.current !== undefined &&
          prevTaskPrivateRef.current !== null &&
          scoreObj.private_score !== null
        ) {
          setFlashPrivate(true);
          t2 = setTimeout(() => setFlashPrivate(false), 2000);
        }
        prevTaskPrivateRef.current = scoreObj.private_score;
      }
    }
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [
    displayPublic,
    displayPrivate,
    displayPoints,
    scoreObj.public_score,
    scoreObj.private_score,
    activeTab,
    isStageTab,
  ]);

  const activeTasks = React.useMemo(() => {
    if (activeTab === 'general') {
      return tasks;
    } else if (isStageTab) {
      return tasks.filter((t) => t.stage_id === activeTab);
    } else {
      return activeTask ? [activeTask] : [];
    }
  }, [activeTab, isStageTab, tasks, activeTask]);

  let colSpanCount = 3;
  if (activeTab === 'general' || isStageTab) {
    colSpanCount += 1;
    if (showPrivateCols) colSpanCount += 1;
    if (showPointsCols) colSpanCount += 1;
  } else {
    if (showPublicCols) colSpanCount++;
    if (perTaskShowPrivateCols) colSpanCount++;
    if (perTaskShowPointsCols) colSpanCount++;
  }

  const isTaskEditingBlocked = (task) => {
    if (!task) return true;
    if (challenge?.scores_finalized && challenge?.reveal_results) {
      return true;
    }
    if (task.stage_id && challenge?.stages) {
      const stage = challenge.stages.find((st) => st.id === task.stage_id);
      if (stage && stage.is_finalized && stage.reveal_results) {
        return true;
      }
    }
    return false;
  };

  const renderManualPointsBadge = (task, pts) => {
    if (isBaseline) return '—';
    const blocked = isTaskEditingBlocked(task);
    const canEdit = isJury && !blocked;

    if (canEdit) {
      return (
        <button
          onClick={() => onEditPoints && onEditPoints(entry.user, task, pts)}
          className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border border-amber-500/30 font-bold font-mono transition-colors cursor-pointer text-xs"
          title={t('leaderboard.edit_points_tooltip', 'Click to edit manual points')}
        >
          <Pencil size={10} className="stroke-[2.5]" />
          {t('leaderboard.points_short', { count: pts })}
        </button>
      );
    }

    return (
      <span className="text-amber-400 font-semibold font-mono">
        {t('leaderboard.points_short', { count: pts })}
      </span>
    );
  };

  const handleDownloadSubmission = async (taskId) => {
    if (!entry.user) return;
    try {
      const res = await ChallengeService.downloadSubmission(challengeId, taskId, entry.user.id);
      if (!res.ok) {
        showToast(
          t('leaderboard.download_submission_failed', 'Download submission failed'),
          'error',
        );
        return;
      }
      const blob = await res.blob();
      const filename = `submission_${entry.user.username || entry.user.alias_id}_task_${taskId}.ipynb`;
      const link = document.createElement('a');
      link.href = window.URL.createObjectURL(blob);
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      showToast(t('leaderboard.submission_downloaded', 'Submission downloaded successfully'));
    } catch {
      showToast(
        t('leaderboard.download_submission_error', 'Error downloading submission'),
        'error',
      );
    }
  };

  return (
    <>
      <tr
        ref={rowRef}
        className={`border-b border-slate-800/60 transition-colors duration-150 ${isCurrentUser ? 'bg-indigo-500/5' : ''}`}
      >
        <td className="px-4 py-3 text-center w-10">
          {!isBaseline && (
            <button
              onClick={onToggleExpand}
              className="text-slate-500 hover:text-slate-300 transition-colors cursor-pointer p-1"
              title={t('leaderboard.toggle_details_tooltip', 'Toggle details')}
            >
              <ChevronRight
                size={14}
                className={`transform transition-transform duration-200 ${isExpanded ? 'rotate-90 text-indigo-400' : ''}`}
              />
            </button>
          )}
        </td>

        <td className="px-4 py-3 text-center w-14 text-slate-300">
          {isBaseline ? (
            <span className="text-xs text-slate-500 font-mono">—</span>
          ) : entry.rank == null ? (
            <span className="text-xs text-slate-500 font-mono">—</span>
          ) : (
            <div
              className={`flex items-center justify-center w-7 h-7 rounded-full border-2 mx-auto ${medalStyle || 'bg-slate-800/60 border-slate-700/60'}`}
              title={t('leaderboard.rank_tooltip', { rank })}
            >
              <span
                className={`text-xs font-extrabold font-mono ${medalStyle ? 'drop-shadow-[0_1px_1px_rgba(0,0,0,0.3)]' : 'text-slate-400'}`}
              >
                {rank}
              </span>
            </div>
          )}
        </td>

        <td className="px-4 py-3 text-left min-w-[150px]">
          {entry.is_baseline_entry ? (
            <div className="flex items-center gap-2">
              <span className="text-sm font-extrabold px-3 py-1 rounded-full border border-indigo-500/40 bg-indigo-500/10 text-indigo-400">
                {t('leaderboard.baseline_label')}
              </span>
            </div>
          ) : showIdentity ? (
            <div className="flex items-center gap-2 text-sm font-bold text-slate-100">
              <span className="truncate">
                {entry.user
                  ? entry.user.name
                    ? `${entry.user.name} ${entry.user.surname}`
                    : entry.user.username
                  : '—'}
              </span>
              {isCurrentUser && (
                <span className="text-[10px] font-extrabold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
                  {t('leaderboard.you_badge')}
                </span>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-semibold text-slate-200">
                {entry.user?.alias_id || '—'}
              </span>
            </div>
          )}
        </td>

        {activeTab === 'general' || isStageTab ? (
          <>
            <td
              className={`px-4 py-3 text-right font-mono text-indigo-400 text-xs transition-all duration-300 ${flashPublic ? 'animate-pulse-highlight' : ''}`}
            >
              {displayPublic != null ? displayPublic.toFixed(4) : '—'}
            </td>
            {showPrivateCols && (
              <td
                className={`px-4 py-3 text-right font-mono text-emerald-400 text-xs transition-all duration-300 ${flashPrivate ? 'animate-pulse-highlight' : ''}`}
              >
                {displayPrivate != null ? displayPrivate.toFixed(4) : '—'}
              </td>
            )}
            {showPointsCols && (
              <td
                className={`px-4 py-3 text-right font-mono font-bold text-xs transition-all duration-300 ${flashPoints ? 'animate-pulse-highlight' : ''}`}
              >
                <span className="text-amber-400">
                  {isBaseline ? '—' : t('leaderboard.points_short', { count: displayPoints })}
                </span>
              </td>
            )}
          </>
        ) : (
          <>
            {showPublicCols && (
              <td
                className={`px-4 py-3 text-right font-mono text-indigo-400 text-xs transition-all duration-300 ${flashPublic ? 'animate-pulse-highlight' : ''}`}
              >
                {scoreObj.public_score != null ? scoreObj.public_score.toFixed(4) : '—'}
              </td>
            )}
            {perTaskShowPrivateCols && (
              <td
                className={`px-4 py-3 text-right font-mono text-emerald-400 text-xs transition-all duration-300 ${flashPrivate ? 'animate-pulse-highlight' : ''}`}
              >
                {scoreObj.private_score != null ? scoreObj.private_score.toFixed(4) : '—'}
              </td>
            )}
            {perTaskShowPointsCols && (
              <td className="px-4 py-3 text-right">
                {renderManualPointsBadge(
                  activeTask,
                  entry.user?.manual_points?.[activeTask.id.toString()] ?? 0,
                )}
              </td>
            )}
          </>
        )}
      </tr>

      {isExpanded && (
        <tr className="bg-slate-900/40 border-b border-slate-800/60">
          <td colSpan={colSpanCount} className="px-6 py-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs animate-fadein">
              <div className="flex flex-col gap-2 border-r border-slate-800/40 pr-6 last:border-r-0">
                <h4 className="font-extrabold text-indigo-400 uppercase tracking-wider text-[9px] mb-1">
                  {t('leaderboard.competitor_demographics')}
                </h4>
                <div className="flex flex-col gap-1.5 text-slate-300">
                  <div>
                    <span className="text-slate-500 font-medium">
                      {t('leaderboard.real_name')}{' '}
                    </span>
                    <span className="font-semibold text-slate-200">
                      {showDemographics ? (
                        entry.user.name ? (
                          `${entry.user.name} ${entry.user.surname}`
                        ) : (
                          entry.user.username
                        )
                      ) : (
                        <span className="italic text-slate-500">{t('leaderboard.anonymous')}</span>
                      )}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium">{t('leaderboard.school')} </span>
                    <span className="text-slate-200">
                      {showDemographics && entry.user.school ? entry.user.school : '—'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium">{t('leaderboard.grade')} </span>
                    <span className="text-slate-200">
                      {showDemographics && entry.user.grade
                        ? t('leaderboard.grade_value', { grade: entry.user.grade })
                        : '—'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium">{t('leaderboard.city')} </span>
                    <span className="text-slate-200">
                      {showDemographics && entry.user.city ? entry.user.city : '—'}
                    </span>
                  </div>
                </div>
              </div>

              {activeTab === 'general' || isStageTab ? (
                <div className="flex flex-col gap-2 border-r border-slate-800/40 pr-6 last:border-r-0 col-span-2">
                  <h4 className="font-extrabold text-indigo-400 uppercase tracking-wider text-[9px] mb-1">
                    {t('leaderboard.detailed_breakdown')}
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 font-sans text-slate-300">
                    {activeTasks.map((task) => {
                      const scObj = entry.task_scores?.[task.id.toString()] || {};
                      const manualPts = entry.user?.manual_points?.[task.id.toString()] ?? 0;
                      return (
                        <div
                          key={task.id}
                          className="p-3 bg-slate-900/40 border border-slate-800/50 rounded-xl flex flex-col gap-1.5"
                        >
                          <div
                            className="font-bold text-slate-200 truncate max-w-[180px]"
                            title={task.title}
                          >
                            {task.title}
                          </div>
                          <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-slate-400">
                            {showPublicCols && (
                              <div>
                                {t('leaderboard.public_score_short')}{' '}
                                <span className="text-indigo-400">
                                  {scObj.public_score != null ? scObj.public_score.toFixed(4) : '—'}
                                </span>
                              </div>
                            )}
                            {showPrivateCols && (
                              <div>
                                {t('leaderboard.private_score_short')}{' '}
                                <span className="text-emerald-400">
                                  {scObj.private_score != null
                                    ? scObj.private_score.toFixed(4)
                                    : '—'}
                                </span>
                              </div>
                            )}
                          </div>
                          {showPointsCols && (
                            <div className="flex items-center justify-between mt-1 pt-1.5 border-t border-slate-800/40 text-xs">
                              <span className="text-slate-500">
                                {t('leaderboard.manual_points_label')}
                              </span>
                              {renderManualPointsBadge(task, manualPts)}
                            </div>
                          )}
                          {isJuryOrAdmin && scObj.submission_id != null && (
                            <div className="flex items-center justify-start mt-1 pt-1.5 border-t border-slate-800/40 text-xs">
                              <button
                                onClick={() => handleDownloadSubmission(task.id)}
                                className="flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 font-bold transition-colors cursor-pointer text-[10px]"
                                title={t('leaderboard.download_solution', 'Download Solution')}
                              >
                                <Download size={10} />
                                {t('leaderboard.download_solution', 'Download Solution')}
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-2 border-r border-slate-800/40 pr-6 last:border-r-0 col-span-2">
                  {isJuryOrAdmin && scoreObj.submission_id != null && (
                    <>
                      <h4 className="font-extrabold text-indigo-400 uppercase tracking-wider text-[9px] mb-1">
                        {t('leaderboard.submission')}
                      </h4>
                      <div className="p-3 bg-slate-900/40 border border-slate-800/50 rounded-xl flex justify-start">
                        <button
                          onClick={() => handleDownloadSubmission(activeTask.id)}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 font-bold transition-colors cursor-pointer text-xs"
                          title={t('leaderboard.download_solution', 'Download Solution')}
                        >
                          <Download size={12} />
                          {t('leaderboard.download_solution', 'Download Solution')}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
