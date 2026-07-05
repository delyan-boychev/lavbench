import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { useAuth } from '../../AuthContext';
import ChallengeService from '../../services/ChallengeService';
import { useApp } from '../../context/AppContext';
import Button from '../ui/Button';
import Modal from '../ui/Modal';
import TabScrollContainer from '../ui/TabScrollContainer';
import EmptyState from '../ui/EmptyState';
import { useTranslation } from 'react-i18next';
import {
  ChevronRight,
  RefreshCw,
  BarChart3,
  Layers,
  CheckSquare,
  Download,
  Pencil,
} from 'lucide-react';
import Badge from '../ui/Badge';

const MEDAL_STYLES = [
  'bg-gradient-to-br from-amber-400 to-amber-600 text-amber-950 border-amber-300 shadow-[0_0_8px_rgba(251,191,36,0.3)]',
  'bg-gradient-to-br from-slate-300 to-slate-400 text-slate-800 border-slate-200 shadow-[0_0_6px_rgba(148,163,184,0.25)]',
  'bg-gradient-to-br from-amber-600 to-amber-800 text-amber-100 border-amber-500/60 shadow-[0_0_5px_rgba(180,83,9,0.2)]',
];

function Row({
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

  // Calculate colSpan dynamically for expanded row
  let colSpanCount = 3; // Toggle expand, rank, participant
  if (activeTab === 'general' || isStageTab) {
    colSpanCount += 1; // Summed Public Score
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
        {/* Toggle Expand column */}
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

        {/* Rank column */}
        <td className="px-4 py-3 text-center w-14 text-slate-300">
          {isBaseline ? (
            <span className="text-xs text-slate-500 font-mono">—</span>
          ) : !entry.has_submitted ? (
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

        {/* Participant Details */}
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

        {/* Dynamic score cells depending on activeTab */}
        {activeTab === 'general' || isStageTab ? (
          <>
            {/* Summed Public Score */}
            <td
              className={`px-4 py-3 text-right font-mono text-indigo-400 text-xs transition-all duration-300 ${flashPublic ? 'animate-pulse-highlight' : ''}`}
            >
              {displayPublic != null ? displayPublic.toFixed(4) : '—'}
            </td>
            {/* Summed Private Score */}
            {showPrivateCols && (
              <td
                className={`px-4 py-3 text-right font-mono text-emerald-400 text-xs transition-all duration-300 ${flashPrivate ? 'animate-pulse-highlight' : ''}`}
              >
                {displayPrivate != null ? displayPrivate.toFixed(4) : '—'}
              </td>
            )}
            {/* Summed Jury/Manual Points */}
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

      {/* Expanded Demographics & Task Breakdown */}
      {isExpanded && (
        <tr className="bg-slate-900/40 border-b border-slate-800/60">
          <td colSpan={colSpanCount} className="px-6 py-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs animate-fadein">
              {/* Demographics */}
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

              {/* Task breakdown OR Task-specific Submission */}
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
                /* Task Specific Submission Section */
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

export default function LeaderboardTable({
  data,
  tasks,
  challenge,
  loading,
  onRefresh,
  metricName,
  isNormalized,
}) {
  const { currentUser } = useAuth();
  const { showToast } = useApp();
  const { t } = useTranslation();
  const isFinalized = challenge?.scores_finalized;
  const metric = metricName || challenge?.metric_name || 'Score';
  const isJuryOrAdmin = currentUser?.role === 'admin' || currentUser?.role === 'jury';

  const isCompetitor = currentUser?.role === 'competitor';

  const challengeStages = challenge?.stages;
  const [activeTab, setActiveTab] = useState('general');
  const [expandedUserIds, setExpandedUserIds] = useState(new Set());
  const revealResults = challenge?.reveal_results;

  const visibleStages = React.useMemo(() => {
    const now = new Date();
    if (!isCompetitor) return challengeStages || [];
    return challengeStages?.filter((st) => new Date(st.start_time) <= now) || [];
  }, [challengeStages, isCompetitor]);

  const isStageTab = visibleStages.some((st) => st.id === activeTab);

  const visibleTasks = React.useMemo(() => {
    const now = new Date();
    if (!isCompetitor) return tasks || [];
    return (
      tasks?.filter((task) => {
        if (!task.stage_id) return true;
        const stage = challengeStages?.find((st) => st.id === task.stage_id);
        return stage ? new Date(stage.start_time) <= now : false;
      }) || []
    );
  }, [tasks, challengeStages, isCompetitor]);

  const [scoringModalOpen, setScoringModalOpen] = useState(false);
  const [scoringUser, setScoringUser] = useState(null);
  const [scoringTask, setScoringTask] = useState(null);
  const [scoringPoints, setScoringPoints] = useState('');
  const [scoringReason, setScoringReason] = useState('');

  const handleEditPoints = (user, task, currentPts) => {
    setScoringUser(user);
    setScoringTask(task);
    setScoringPoints(currentPts ? currentPts.toString() : '0');
    setScoringReason('');
    setScoringModalOpen(true);
  };

  const isReasonMandatory = React.useMemo(() => {
    return !!challenge?.scores_finalized;
  }, [challenge]);

  const handleSavePointsSubmit = async () => {
    const pts = parseInt(scoringPoints);
    if (isNaN(pts) || pts < 0 || pts > 100) {
      showToast(t('leaderboard.save_points_error'), 'error');
      return;
    }
    if (isReasonMandatory && !scoringReason.trim()) {
      showToast(
        t('leaderboard.reason_required_error', 'Justification reason is required.'),
        'error',
      );
      return;
    }

    try {
      const res = await ChallengeService.saveManualPoints(challenge.id, {
        user_id: scoringUser.id,
        points: { [scoringTask.id]: pts },
        reason: scoringReason.trim() || undefined,
      });

      if (res.ok) {
        showToast(
          t('leaderboard.save_points_success', {
            pts,
            name: scoringUser.name || scoringUser.username || scoringUser.alias_id,
          }),
        );
        setScoringModalOpen(false);
        if (onRefresh) onRefresh();
      } else {
        const errData = /** @type {any} */ (res.data);
        const errCode = errData?.code;
        const errMsg = errCode
          ? t(`api.${errCode}`, errData?.error)
          : t('leaderboard.save_points_failed');
        showToast(errMsg, 'error');
      }
    } catch {
      showToast(t('leaderboard.server_error'), 'error');
    }
  };

  const rowElementsRef = useRef({});
  const rowPositionsRef = useRef({});

  useLayoutEffect(() => {
    const oldPositions = rowPositionsRef.current;
    const newPositions = {};
    Object.keys(rowElementsRef.current).forEach((key) => {
      const el = rowElementsRef.current[key];
      if (el) {
        newPositions[key] = el.getBoundingClientRect().top;
      }
    });

    Object.entries(newPositions).forEach(([key, newTop]) => {
      const oldTop = oldPositions[key];
      if (oldTop !== undefined) {
        const delta = oldTop - newTop;
        if (Math.abs(delta) > 0.5) {
          const el = rowElementsRef.current[key];
          if (el) {
            el.animate([{ transform: `translateY(${delta}px)` }, { transform: 'translateY(0)' }], {
              duration: 600,
              easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
            });
          }
        }
      }
    });

    rowPositionsRef.current = newPositions;
  });

  const handleToggleExpand = (userId) => {
    setExpandedUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  };

  if (loading) {
    return (
      <EmptyState minHeight={150} message={t('leaderboard.loading')}>
        <div className="animate-spin w-6 h-6 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
      </EmptyState>
    );
  }
  // Calculate Sub-column visibility rules
  const showPublicCols = true;

  // Data-driven checks: only show columns that have actual data
  const hasPrivateData = data.some((e) => e.private_score != null);
  const hasPointsData = data.some((e) => e.total_points > 0);

  // Determine if current stage tab has its own reveal
  const activeStage = isStageTab ? visibleStages.find((st) => st.id === activeTab) : null;
  const stageRevealed = activeStage && activeStage.is_finalized && activeStage.reveal_results;

  // Any revealed stage makes private/points columns relevant in the general tab too
  const anyStageRevealed = visibleStages.some((st) => st.is_finalized && st.reveal_results);

  const showPrivateCols =
    (isJuryOrAdmin ||
      (isFinalized && revealResults) ||
      (!isJuryOrAdmin &&
        !isFinalized &&
        (stageRevealed || (activeTab === 'general' && anyStageRevealed)))) &&
    hasPrivateData;
  const showPointsCols =
    (isJuryOrAdmin ||
      (isFinalized && revealResults) ||
      (!isJuryOrAdmin &&
        !isFinalized &&
        (stageRevealed || (activeTab === 'general' && anyStageRevealed)))) &&
    hasPointsData;

  // Per-task tab visibility: check the specific task's stage reveal status
  const activeTaskForPerTab =
    !isStageTab && activeTab !== 'general' ? tasks.find((t) => t.id === activeTab) : null;
  const taskStage = activeTaskForPerTab?.stage_id
    ? challengeStages?.find((st) => st.id === activeTaskForPerTab.stage_id)
    : null;
  const taskStageRevealed = taskStage?.is_finalized && taskStage?.reveal_results;

  const perTaskShowPrivateCols =
    isJuryOrAdmin ||
    (isFinalized && revealResults) ||
    (!isJuryOrAdmin && !isFinalized && taskStageRevealed);

  const perTaskShowPointsCols =
    isJuryOrAdmin ||
    (isFinalized && revealResults) ||
    (!isJuryOrAdmin && !isFinalized && taskStageRevealed);

  // Competition status for the header badge
  const competitionStatus = isFinalized
    ? revealResults
      ? 'public'
      : 'internal'
    : challenge?.start_time && new Date() < new Date(challenge.start_time)
      ? 'future'
      : challenge?.end_time && new Date() > new Date(challenge.end_time)
        ? 'grading'
        : 'active';
  // 1. Sort and rank display data dynamically based on active tab
  let displayData = [...data];

  // Baseline entries never appear in general or stage tabs (only per-task)
  if (activeTab === 'general' || isStageTab) {
    displayData = displayData.filter((e) => !e.is_baseline_entry);
  } else if (activeTab !== 'general') {
    displayData = displayData.filter((e) => {
      if (!e.is_baseline_entry) return true;
      return e.task_scores?.[activeTab.toString()]?.submission_id != null;
    });
  }

  // After filtering baselines, recompute ranks for remaining entries
  let currentRank = 0;
  displayData = displayData.map((entry) => {
    const entryCopy = { ...entry };
    const hasScore = entry.has_submitted;
    if (hasScore) {
      currentRank += 1;
    }
    entryCopy.rank = hasScore ? currentRank : null;
    return entryCopy;
  });

  const isMse = (challenge?.metric_name || '').toLowerCase() in { mse: 1, loss: 1, error: 1 };

  if (isStageTab) {
    const stageTasks = visibleTasks.filter((t) => t.stage_id === activeTab);
    displayData.sort((a, b) => {
      let hasPubA = false;
      let pubSumA = 0;
      let ptsSumA = 0;
      stageTasks.forEach((t) => {
        const sc = a.task_scores?.[t.id.toString()];
        if (sc && sc.public_score != null) {
          pubSumA += sc.public_score;
          hasPubA = true;
        }
        ptsSumA += a.user?.manual_points?.[t.id.toString()] ?? 0;
      });

      let hasPubB = false;
      let pubSumB = 0;
      let ptsSumB = 0;
      stageTasks.forEach((t) => {
        const sc = b.task_scores?.[t.id.toString()];
        if (sc && sc.public_score != null) {
          pubSumB += sc.public_score;
          hasPubB = true;
        }
        ptsSumB += b.user?.manual_points?.[t.id.toString()] ?? 0;
      });

      if (isFinalized && (isJuryOrAdmin || revealResults)) {
        if (ptsSumA !== ptsSumB) return ptsSumB - ptsSumA;
      } else if (stageRevealed) {
        // Stage is revealed — sort by points for this stage
        if (ptsSumA !== ptsSumB) return ptsSumB - ptsSumA;
      } else {
        if (hasPubA && hasPubB) {
          if (pubSumA !== pubSumB) return pubSumB - pubSumA;
        } else if (hasPubA) {
          return -1;
        } else if (hasPubB) {
          return 1;
        }
      }

      // Fallback name stable sort
      const nameA = (
        (a.user?.name ? `${a.user.name} ${a.user.surname}` : a.user?.username) ||
        a.user?.alias_id ||
        ''
      ).toLowerCase();
      const nameB = (
        (b.user?.name ? `${b.user.name} ${b.user.surname}` : b.user?.username) ||
        b.user?.alias_id ||
        ''
      ).toLowerCase();
      return nameA.localeCompare(nameB);
    });

    let currentRank = 0;
    displayData = displayData.map((entry, index) => {
      const entryCopy = { ...entry };
      let userHasSubmitted = false;
      if (!entry.is_baseline_entry) {
        stageTasks.forEach((t) => {
          if (entry.task_scores?.[t.id.toString()]?.submission_id != null) {
            userHasSubmitted = true;
          }
        });

        if (userHasSubmitted) {
          currentRank += 1;
        }

        // Tie detection only for submitters
        if (userHasSubmitted) {
          let prevIdx = index - 1;
          let prevNonBaseline = null;
          while (prevIdx >= 0) {
            const candidate = displayData[prevIdx];
            if (!candidate.is_baseline_entry && candidate.task_scores) {
              const candidateSubmitted = stageTasks.some(
                (t) => candidate.task_scores?.[t.id.toString()]?.submission_id != null,
              );
              if (candidateSubmitted) {
                prevNonBaseline = candidate;
                break;
              }
            }
            prevIdx--;
          }

          if (prevNonBaseline) {
            let prevPub = 0;
            let prevPts = 0;
            stageTasks.forEach((t) => {
              prevPub += prevNonBaseline.task_scores?.[t.id.toString()]?.public_score ?? 0;
              prevPts += prevNonBaseline.user?.manual_points?.[t.id.toString()] ?? 0;
            });

            let currPub = 0;
            let currPts = 0;
            stageTasks.forEach((t) => {
              currPub += entry.task_scores?.[t.id.toString()]?.public_score ?? 0;
              currPts += entry.user?.manual_points?.[t.id.toString()] ?? 0;
            });

            let isTie;
            if ((isFinalized && (isJuryOrAdmin || revealResults)) || stageRevealed) {
              isTie = currPts === prevPts;
            } else {
              isTie = currPub === prevPub;
            }

            if (isTie) {
              currentRank = prevNonBaseline.rank;
            }
          }
        }
      }
      entryCopy.rank = userHasSubmitted ? currentRank : null;
      entryCopy.has_submitted = userHasSubmitted;
      return entryCopy;
    });
  } else if (activeTab !== 'general') {
    const activeTaskIdStr = activeTab.toString();
    displayData.sort((a, b) => {
      if (isFinalized && (isJuryOrAdmin || revealResults)) {
        const ptsA = Number(a.user?.manual_points?.[activeTaskIdStr] ?? 0);
        const ptsB = Number(b.user?.manual_points?.[activeTaskIdStr] ?? 0);
        if (ptsA !== ptsB) return ptsB - ptsA;
      } else {
        const scoreA = a.task_scores?.[activeTaskIdStr]?.public_score;
        const scoreB = b.task_scores?.[activeTaskIdStr]?.public_score;

        if (scoreA != null && scoreB != null) {
          if (scoreA !== scoreB) {
            return isMse ? scoreA - scoreB : scoreB - scoreA;
          }
        } else if (scoreA != null) {
          return -1;
        } else if (scoreB != null) {
          return 1;
        }
      }

      // Fallback name stable sort
      const nameA = (
        (a.user?.name ? `${a.user.name} ${a.user.surname}` : a.user?.username) ||
        a.user?.alias_id ||
        ''
      ).toLowerCase();
      const nameB = (
        (b.user?.name ? `${b.user.name} ${b.user.surname}` : b.user?.username) ||
        b.user?.alias_id ||
        ''
      ).toLowerCase();
      return nameA.localeCompare(nameB);
    });

    let currentRank = 0;
    displayData = displayData.map((entry, index) => {
      const entryCopy = { ...entry };
      const hasScore =
        !entry.is_baseline_entry && entry.task_scores?.[activeTaskIdStr]?.submission_id != null;
      if (!entry.is_baseline_entry) {
        // Only rank entries that have submitted
        if (hasScore) {
          // eslint-disable-next-line react-hooks/immutability
          currentRank += 1;
        }
        // Tie comparison only for submitters
        if (hasScore) {
          let prevIdx = index - 1;
          let prevNonBaseline = null;
          while (prevIdx >= 0) {
            const candidate = displayData[prevIdx];
            if (
              !candidate.is_baseline_entry &&
              candidate.task_scores?.[activeTaskIdStr]?.submission_id != null
            ) {
              prevNonBaseline = candidate;
              break;
            }
            prevIdx--;
          }
          if (prevNonBaseline) {
            let isTie;
            if (isFinalized && (isJuryOrAdmin || revealResults)) {
              const ptsA = Number(entry.user?.manual_points?.[activeTaskIdStr] ?? 0);
              const ptsB = Number(prevNonBaseline.user?.manual_points?.[activeTaskIdStr] ?? 0);
              isTie = ptsA === ptsB;
            } else {
              const scoreA = entry.task_scores?.[activeTaskIdStr]?.public_score;
              const scoreB = prevNonBaseline.task_scores?.[activeTaskIdStr]?.public_score;
              isTie = scoreA != null && scoreB != null && scoreA === scoreB;
            }
            if (isTie) {
              currentRank = prevNonBaseline.rank;
            }
          }
        }
      }
      entryCopy.rank = hasScore ? currentRank : null;
      entryCopy.has_submitted = hasScore;
      return entryCopy;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div className="flex items-center gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-100">{t('leaderboard.title')}</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {t('leaderboard.metric')}{' '}
              <span className="text-indigo-400 font-semibold">{metric}</span>
              {isNormalized && (
                <span
                  className="text-[10px] text-slate-500 ml-1"
                  title={t('leaderboard.normalized_hint')}
                >
                  {t('leaderboard.normalized')}
                </span>
              )}
              {' · '}
              {t('leaderboard.participants', { count: data.length })}
              <span className="ml-2">
                <Badge status={competitionStatus} />
              </span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onRefresh && onRefresh()}
              className="p-2 rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-slate-800 transition-colors"
              title={t('leaderboard.refresh')}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Tabs for General Standings vs Stages vs Tasks */}
      <div className="flex flex-col gap-3 w-full border-b border-slate-800 pb-3">
        {/* Overview Row */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
          <div className="flex items-center gap-1.5 text-slate-400 min-w-[100px] sm:min-w-[120px] flex-shrink-0">
            <BarChart3 size={14} className="text-indigo-400" />
            <span className="text-[10px] font-extrabold uppercase tracking-wider">
              {t('leaderboard.tab_group_overview')}
            </span>
          </div>
          <div className="flex-grow min-w-0">
            <TabScrollContainer>
              <div className="flex gap-1.5 flex-nowrap py-0.5">
                <button
                  onClick={() => setActiveTab('general')}
                  className={`px-4 py-2 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${
                    activeTab === 'general'
                      ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 shadow-inner'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent'
                  }`}
                >
                  {t('leaderboard.general_tab')}
                </button>
              </div>
            </TabScrollContainer>
          </div>
        </div>

        {/* Stages Row */}
        {visibleStages.length > 0 && (
          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
            <div className="flex items-center gap-1.5 text-slate-400 min-w-[100px] sm:min-w-[120px] flex-shrink-0">
              <Layers size={14} className="text-emerald-400" />
              <span className="text-[10px] font-extrabold uppercase tracking-wider">
                {t('leaderboard.tab_group_stages')}
              </span>
            </div>
            <div className="flex-grow min-w-0">
              <TabScrollContainer>
                <div className="flex gap-1.5 flex-nowrap py-0.5">
                  {visibleStages.map((stage) => (
                    <button
                      key={stage.id}
                      onClick={() => setActiveTab(stage.id)}
                      className={`px-4 py-2 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer flex-shrink-0 ${
                        activeTab === stage.id
                          ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 shadow-inner'
                          : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent'
                      }`}
                    >
                      {t('challenge.stage_title', {
                        number: stage.stage_number,
                        title: stage.title,
                      })}
                      {(() => {
                        const now = new Date();
                        const start = new Date(stage.start_time);
                        const end = new Date(stage.end_time);
                        let stStatus;
                        if (stage.is_finalized && stage.reveal_results) {
                          stStatus = 'public';
                        } else if (stage.is_finalized && !stage.reveal_results) {
                          stStatus = 'internal';
                        } else if (now > end) {
                          stStatus = 'grading';
                        } else if (now < start) {
                          stStatus = 'future';
                        } else {
                          stStatus = 'active';
                        }
                        return (
                          <span className="ml-1.5">
                            <Badge status={stStatus} />
                          </span>
                        );
                      })()}
                    </button>
                  ))}
                </div>
              </TabScrollContainer>
            </div>
          </div>
        )}

        {/* Tasks Row */}
        {visibleTasks.length > 0 && (
          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
            <div className="flex items-center gap-1.5 text-slate-400 min-w-[100px] sm:min-w-[120px] flex-shrink-0">
              <CheckSquare size={14} className="text-amber-400" />
              <span className="text-[10px] font-extrabold uppercase tracking-wider">
                {t('leaderboard.tab_group_tasks')}
              </span>
            </div>
            <div className="flex-grow min-w-0">
              <TabScrollContainer>
                <div className="flex gap-1.5 flex-nowrap py-0.5">
                  {visibleTasks.map((task) => (
                    <button
                      key={task.id}
                      onClick={() => setActiveTab(task.id)}
                      className={`px-4 py-2 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer flex-shrink-0 ${
                        activeTab === task.id
                          ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 shadow-inner'
                          : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent'
                      }`}
                    >
                      {task.title}
                    </button>
                  ))}
                </div>
              </TabScrollContainer>
            </div>
          </div>
        )}
      </div>

      {/* Finalized Internal Notice */}
      {isStageTab && activeStage?.is_finalized && !activeStage?.reveal_results && (
        <div className="px-4 py-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-xs text-amber-300 mb-3">
          {t(
            'leaderboard.stage_finalized_internal_notice',
            'This stage is finalized internally. Results are not public.',
          )}
        </div>
      )}

      {/* Table */}
      <div className="surface overflow-hidden">
        {displayData.length === 0 ? (
          <EmptyState
            surface={false}
            message={t('leaderboard.no_submissions')}
            icon={<BarChart3 size={32} className="text-slate-500" />}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3 text-center w-10"></th>
                  <th className="px-4 py-3 text-center w-14">#</th>
                  <th className="px-4 py-3 text-left">{t('leaderboard.participant_header')}</th>

                  {activeTab === 'general' || isStageTab ? (
                    <>
                      <th className="px-4 py-3 text-right text-indigo-400 text-[10px] font-bold whitespace-nowrap">
                        {t('leaderboard.summed_public_score', 'Summed Public Score')}
                      </th>
                      {showPrivateCols && (
                        <th className="px-4 py-3 text-right text-emerald-400 text-[10px] font-bold whitespace-nowrap">
                          {t('leaderboard.summed_private_score', 'Summed Private Score')}
                        </th>
                      )}
                      {showPointsCols && (
                        <th className="px-4 py-3 text-right text-amber-500 text-[10px] font-extrabold uppercase tracking-wider whitespace-nowrap">
                          {t('leaderboard.total_points')}
                        </th>
                      )}
                    </>
                  ) : (
                    <>
                      {showPublicCols && (
                        <th className="px-4 py-3 text-right text-indigo-400 text-[10px] font-bold whitespace-nowrap">
                          {t('leaderboard.public_score')}
                        </th>
                      )}
                      {perTaskShowPrivateCols && (
                        <th className="px-4 py-3 text-right text-emerald-400 text-[10px] font-bold whitespace-nowrap">
                          {t('leaderboard.private_score')}
                        </th>
                      )}
                      {perTaskShowPointsCols && (
                        <th className="px-4 py-3 text-right text-amber-400 text-[10px] font-bold whitespace-nowrap">
                          {t('leaderboard.manual_points')}
                        </th>
                      )}
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {displayData.map((entry) => {
                  const key = entry.user?.id || (entry.is_baseline_entry ? 'baseline' : entry.rank);
                  return (
                    <Row
                      key={key}
                      rowRef={(el) => {
                        if (el) {
                          rowElementsRef.current[key] = el;
                        } else {
                          delete rowElementsRef.current[key];
                        }
                      }}
                      entry={entry}
                      rank={entry.rank}
                      tasks={visibleTasks}
                      isCurrentUser={entry.user?.id === currentUser?.id}
                      isFinalized={isFinalized}
                      doubleBlind={challenge?.double_blind !== false}
                      isExpanded={expandedUserIds.has(entry.user?.id)}
                      onToggleExpand={() => handleToggleExpand(entry.user?.id)}
                      challengeId={challenge?.id}
                      showPublicCols={showPublicCols}
                      showPrivateCols={showPrivateCols}
                      showPointsCols={showPointsCols}
                      perTaskShowPrivateCols={perTaskShowPrivateCols}
                      perTaskShowPointsCols={perTaskShowPointsCols}
                      activeTab={activeTab}
                      challenge={challenge}
                      onEditPoints={handleEditPoints}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Points Modal */}
      <Modal
        isOpen={scoringModalOpen}
        onClose={() => setScoringModalOpen(false)}
        title={t('leaderboard.score_competitor_title', 'Score Competitor')}
        footer={
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setScoringModalOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" onClick={handleSavePointsSubmit}>
              {t('common.save', 'Save')}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4 text-sm text-slate-300">
          {/* Task Details */}
          <div>
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-1">
              {t('leaderboard.task_details', 'Task Details')}
            </h4>
            <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
              <span className="font-semibold text-slate-200">{scoringTask?.title}</span>
            </div>
          </div>

          {/* Competitor Details */}
          <div>
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-1">
              {t('leaderboard.competitor_details', 'Competitor Details')}
            </h4>
            <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800 flex flex-col gap-1.5">
              {isFinalized ? (
                <>
                  <div>
                    <span className="text-slate-500">{t('leaderboard.real_name', 'Name')}: </span>
                    <span className="text-slate-200 font-semibold">
                      {scoringUser?.name
                        ? `${scoringUser.name} ${scoringUser.surname}`
                        : scoringUser?.username}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">
                      {t('leaderboard.username', 'Username')}:{' '}
                    </span>
                    <span className="text-slate-200">{scoringUser?.username}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">{t('leaderboard.school', 'School')}: </span>
                    <span className="text-slate-200">{scoringUser?.school || '—'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">{t('leaderboard.grade', 'Grade')}: </span>
                    <span className="text-slate-200">
                      {scoringUser?.grade
                        ? t('leaderboard.grade_value', { grade: scoringUser.grade })
                        : '—'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">{t('leaderboard.city', 'City')}: </span>
                    <span className="text-slate-200">{scoringUser?.city || '—'}</span>
                  </div>
                </>
              ) : (
                <div>
                  <span className="text-slate-500">{t('leaderboard.alias_id', 'Alias')}: </span>
                  <span className="text-slate-200 font-semibold font-mono">
                    {scoringUser?.alias_id}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Points Input */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
              {t('leaderboard.points_input_label', 'Points (0-100)')}
            </label>
            <input
              type="number"
              min="0"
              max="100"
              value={scoringPoints}
              onChange={(e) => setScoringPoints(e.target.value)}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 rounded font-mono text-sm text-indigo-300"
              placeholder="Enter score"
            />
          </div>

          {/* Reason Input (only shown when mandatory after finalization) */}
          {isReasonMandatory && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-slate-400 uppercase tracking-wider flex justify-between">
                <span>{t('leaderboard.reason_label', 'Justification Reason')}</span>
                <span className="text-rose-400 text-[10px] font-extrabold uppercase">
                  {t('common.required', 'Required')}
                </span>
              </label>
              <textarea
                value={scoringReason}
                onChange={(e) => setScoringReason(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 rounded text-sm text-slate-300 resize-none"
                placeholder={t(
                  'leaderboard.reason_required_placeholder',
                  'Enter justification (mandatory)...',
                )}
              />
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
