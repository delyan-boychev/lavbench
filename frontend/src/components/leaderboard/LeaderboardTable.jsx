import React, { useState } from 'react';
import { useAuth } from '../../AuthContext';
import ChallengeService from '../../services/ChallengeService';
import { useApp } from '../../context/AppContext';
import Button from '../ui/Button';
import Modal from '../ui/Modal';
import TabScrollContainer from '../ui/TabScrollContainer';
import EmptyState from '../ui/EmptyState';
import { useTranslation } from 'react-i18next';
import { ChevronRight, RefreshCw, BarChart3 } from 'lucide-react';

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
  onRefresh,
  activeTab,
}) {
  const { currentUser } = useAuth();
  const { showToast } = useApp();
  const { t } = useTranslation();
  const isAdmin = currentUser?.role === 'admin';
  const isJury = currentUser?.role === 'jury';
  const showIdentity = !doubleBlind || isFinalized || isCurrentUser || isAdmin;
  const showDemographics = showIdentity && (!entry.user?.is_anonymous || isAdmin || isCurrentUser);
  const isBaseline = entry.is_baseline_entry;
  const medalStyle = !isBaseline && rank >= 1 && rank <= 3 ? MEDAL_STYLES[rank - 1] : null;

  const [tempPoints, setTempPoints] = useState({});

  const handlePointsChange = (taskId, value) => {
    setTempPoints((prev) => ({ ...prev, [taskId]: value }));
  };

  const handleSavePoints = async (taskId) => {
    const rawVal = tempPoints[taskId];
    if (rawVal === undefined) return;
    const pts = parseInt(rawVal);
    if (isNaN(pts) || pts < 0 || pts > 100) {
      showToast(t('leaderboard.save_points_error'), 'error');
      return;
    }
    try {
      const res = await ChallengeService.saveManualPoints(challengeId, {
        user_id: entry.user.id,
        points: { [taskId]: pts },
      });
      if (res.ok) {
        showToast(
          t('leaderboard.save_points_success', {
            pts,
            name: entry.user.name || entry.user.username,
          }),
        );
        if (onRefresh) onRefresh();
      } else {
        showToast(res.data?.error || t('leaderboard.save_points_failed'), 'error');
      }
    } catch {
      showToast(t('leaderboard.server_error'), 'error');
    }
  };

  const activeTask = activeTab !== 'general' ? tasks.find((t) => t.id === activeTab) : null;
  const scoreObj = activeTask ? entry.task_scores?.[activeTask.id.toString()] || {} : {};

  // Calculate colSpan dynamically for expanded row
  let colSpanCount = 3; // Toggle expand, rank, participant
  if (activeTab === 'general') {
    if (showPublicCols) colSpanCount++;
    if (showPrivateCols) colSpanCount++;
    if (showPointsCols) colSpanCount++;
  } else {
    if (showPublicCols) colSpanCount++;
    if (showPrivateCols) colSpanCount++;
    if (showPointsCols) colSpanCount++;
  }

  return (
    <>
      <tr
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
        {activeTab === 'general' ? (
          <>
            {showPublicCols && (
              <td className="px-4 py-3 text-right font-mono text-indigo-400 text-xs">
                {entry.public_score != null ? entry.public_score.toFixed(4) : '—'}
              </td>
            )}
            {showPrivateCols && (
              <td className="px-4 py-3 text-right font-mono text-emerald-400 text-xs">
                {entry.private_score != null ? entry.private_score.toFixed(4) : '—'}
              </td>
            )}
            {showPointsCols && (
              <td className="px-4 py-3 text-right font-mono font-bold text-sm">
                <span className="text-amber-400">
                  {isBaseline ? '—' : t('leaderboard.points_short', { count: entry.total_points })}
                </span>
              </td>
            )}
          </>
        ) : (
          <>
            {showPublicCols && (
              <td className="px-4 py-3 text-right font-mono text-indigo-400 text-xs">
                {scoreObj.public_score != null ? scoreObj.public_score.toFixed(4) : '—'}
              </td>
            )}
            {showPrivateCols && (
              <td className="px-4 py-3 text-right font-mono text-emerald-400 text-xs">
                {scoreObj.private_score != null ? scoreObj.private_score.toFixed(4) : '—'}
              </td>
            )}
            {showPointsCols && (
              <td className="px-4 py-3 text-right font-mono font-bold text-sm">
                {isJury && !isFinalized && !isBaseline ? (
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={
                      tempPoints[activeTask.id] ??
                      entry.user?.manual_points?.[activeTask.id.toString()] ??
                      0
                    }
                    onChange={(e) => handlePointsChange(activeTask.id, e.target.value)}
                    onBlur={() => handleSavePoints(activeTask.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        /** @type {HTMLElement} */ (e.target).blur();
                      }
                    }}
                    className="w-16 px-1 py-0.5 text-center bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 rounded font-mono text-xs text-indigo-300 inline-block"
                  />
                ) : (
                  <span className="text-amber-400">
                    {isBaseline
                      ? '—'
                      : t('leaderboard.points_short', {
                          count: entry.user?.manual_points?.[activeTask.id.toString()] ?? 0,
                        })}
                  </span>
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

              {/* Task breakdown */}
              <div className="flex flex-col gap-2 border-r border-slate-800/40 pr-6 last:border-r-0 col-span-2">
                <h4 className="font-extrabold text-indigo-400 uppercase tracking-wider text-[9px] mb-1">
                  {t('leaderboard.detailed_breakdown')}
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 font-sans text-slate-300">
                  {tasks.map((task) => {
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
                                {scObj.private_score != null ? scObj.private_score.toFixed(4) : '—'}
                              </span>
                            </div>
                          )}
                        </div>
                        {showPointsCols && (
                          <div className="flex items-center justify-between mt-1 pt-1.5 border-t border-slate-800/40 text-xs">
                            <span className="text-slate-500">
                              {t('leaderboard.manual_points_label')}
                            </span>
                            <span className="text-amber-400 font-bold font-mono">
                              {isBaseline
                                ? '—'
                                : t('leaderboard.points_short', { count: manualPts })}
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
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
  const { showToast, fetchChallenges } = useApp();
  const { t } = useTranslation();
  const isFinalized = challenge?.scores_finalized;
  const metric = metricName || challenge?.metric_name || 'Score';
  const isJury = currentUser?.role === 'jury';
  const isJuryOrAdmin = currentUser?.role === 'admin' || currentUser?.role === 'jury';

  const [activeTab, setActiveTab] = useState('general');
  const [expandedUserIds, setExpandedUserIds] = useState(new Set());
  const [isFinalizeModalOpen, setIsFinalizeModalOpen] = useState(false);
  const [isRevealing, setIsRevealing] = useState(false);

  const handleToggleReveal = async () => {
    setIsRevealing(true);
    const res = await ChallengeService.toggleReveal(challenge.id, !challenge.reveal_results);
    if (res.ok) {
      showToast(
        res.data.reveal_results
          ? t('leaderboard.results_revealed')
          : t('leaderboard.results_hidden'),
      );
      fetchChallenges();
      if (onRefresh) onRefresh();
    }
    setIsRevealing(false);
  };

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

  const handleFinalizeSubmit = async () => {
    setIsFinalizeModalOpen(false);
    const res = await ChallengeService.finalize(challenge.id, {});
    if (res.ok) {
      showToast(
        t('leaderboard.scores_finalized_success', 'Scores finalized — visibility options applied.'),
      );
      fetchChallenges();
      if (onRefresh) onRefresh();
    } else {
      showToast(
        res.data?.error || t('leaderboard.finalize_failed', 'Finalization failed.'),
        'error',
      );
    }
  };

  if (loading) {
    return (
      <EmptyState minHeight={150} message={t('leaderboard.loading')}>
        <div className="animate-spin w-6 h-6 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
      </EmptyState>
    );
  }

  // Calculate Sub-column visibility rules
  const showPublicCols = !isFinalized || isJuryOrAdmin || challenge?.reveal_results;
  const showPrivateCols = isJuryOrAdmin || (isFinalized && challenge?.reveal_results);
  const showPointsCols = isJuryOrAdmin || (isFinalized && challenge?.reveal_results);

  // 1. Sort and rank display data dynamically based on active tab
  let displayData = [...data];

  // Baseline entries never appear in the general tab
  if (activeTab === 'general') {
    displayData = displayData.filter((e) => !e.is_baseline_entry);
  }
  // In per-task tabs, baselines are hidden only after finalization
  if (isFinalized) {
    displayData = displayData.filter((e) => !e.is_baseline_entry);
  }

  const isMse = (challenge?.metric_name || '').toLowerCase() in { mse: 1, loss: 1, error: 1 };

  if (activeTab !== 'general') {
    const activeTaskIdStr = activeTab.toString();
    displayData.sort((a, b) => {
      if (isFinalized) {
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
      if (!entry.is_baseline_entry) {
        // Only rank entries that have submitted
        const hasScore = entry.has_submitted;
        if (hasScore) {
          // eslint-disable-next-line react-hooks/immutability
          currentRank += 1;
        }
        // Find previous non-baseline entry for tie comparison
        let prevIdx = index - 1;
        let prevNonBaseline = null;
        while (prevIdx >= 0) {
          const candidate = displayData[prevIdx];
          if (!candidate.is_baseline_entry) {
            prevNonBaseline = candidate;
            break;
          }
          prevIdx--;
        }
        if (prevNonBaseline) {
          let isTie;
          if (isFinalized) {
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
      entryCopy.rank = currentRank;
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
              {isFinalized && (
                <span className="pill pill-success ml-2">{t('leaderboard.finalized')}</span>
              )}
            </p>
          </div>
          <button
            onClick={() => onRefresh && onRefresh()}
            className="p-2 rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-slate-800 transition-colors"
            title={t('leaderboard.refresh')}
          >
            <RefreshCw size={16} />
          </button>
        </div>
        {/* Only JURY (not admin) can finalize */}
        {isJury && !isFinalized && challenge && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsFinalizeModalOpen(true)}
            disabled={challenge.stages && challenge.stages.some((st) => !st.is_finalized)}
            title={
              challenge.stages && challenge.stages.some((st) => !st.is_finalized)
                ? t('leaderboard.finalize_disabled_tooltip')
                : ''
            }
          >
            {t('leaderboard.finalize_button')}
          </Button>
        )}
        {/* Reveal toggle — jury only, after finalization */}
        {isJury && isFinalized && challenge && (
          <Button variant="secondary" size="sm" onClick={handleToggleReveal} disabled={isRevealing}>
            {challenge?.reveal_results
              ? t('leaderboard.hide_results')
              : t('leaderboard.reveal_results')}
          </Button>
        )}
      </div>

      {/* Tabs for General Standings vs Tasks */}
      <div className="border-b border-slate-800 pb-2 w-full">
        <TabScrollContainer>
          <button
            onClick={() => setActiveTab('general')}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer flex-shrink-0 ${
              activeTab === 'general'
                ? 'bg-indigo-600 text-white shadow-md'
                : 'text-slate-300 hover:bg-slate-800'
            }`}
          >
            {t('leaderboard.general_tab')}
          </button>
          {tasks?.map((task) => (
            <button
              key={task.id}
              onClick={() => setActiveTab(task.id)}
              className={`px-4 py-2 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer flex-shrink-0 ${
                activeTab === task.id
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              {task.title}
            </button>
          ))}
        </TabScrollContainer>
      </div>

      {/* Table */}
      <div key={activeTab} className="surface overflow-hidden animate-fadein">
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

                  {activeTab === 'general' ? (
                    <>
                      {showPublicCols && (
                        <th className="px-4 py-3 text-right">
                          {t('leaderboard.summed_public_score')}
                        </th>
                      )}
                      {showPrivateCols && (
                        <th className="px-4 py-3 text-right">
                          {t('leaderboard.summed_private_score')}
                        </th>
                      )}
                      {showPointsCols && (
                        <th className="px-4 py-3 text-right">{t('leaderboard.total_points')}</th>
                      )}
                    </>
                  ) : (
                    <>
                      {showPublicCols && (
                        <th className="px-4 py-3 text-right">{t('leaderboard.public_score')}</th>
                      )}
                      {showPrivateCols && (
                        <th className="px-4 py-3 text-right">{t('leaderboard.private_score')}</th>
                      )}
                      {showPointsCols && (
                        <th className="px-4 py-3 text-right">{t('leaderboard.manual_points')}</th>
                      )}
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {displayData.map((entry) => (
                  <Row
                    key={entry.user?.id || entry.rank}
                    entry={entry}
                    rank={entry.rank}
                    tasks={tasks || []}
                    isCurrentUser={entry.user?.id === currentUser?.id}
                    isFinalized={isFinalized}
                    doubleBlind={challenge?.double_blind !== false}
                    isExpanded={expandedUserIds.has(entry.user?.id)}
                    onToggleExpand={() => handleToggleExpand(entry.user?.id)}
                    challengeId={challenge?.id}
                    showPublicCols={showPublicCols}
                    showPrivateCols={showPrivateCols}
                    showPointsCols={showPointsCols}
                    onRefresh={onRefresh}
                    activeTab={activeTab}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Finalize Modal — confirm only, no reveal toggle */}
      <Modal
        isOpen={isFinalizeModalOpen}
        onClose={() => setIsFinalizeModalOpen(false)}
        title={t('leaderboard.finalize_modal_title')}
        footer={
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setIsFinalizeModalOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" onClick={handleFinalizeSubmit}>
              {t('leaderboard.finalize_and_reveal')}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-5 text-sm text-slate-300">
          <p>{t('leaderboard.finalize_modal_desc', { title: challenge?.title })}</p>
        </div>
      </Modal>
    </div>
  );
}
