import React, { useState, useLayoutEffect, useRef } from 'react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Button from '../ui/Button';
import Modal from '../ui/Modal';
import TabScrollContainer from '../ui/TabScrollContainer';
import EmptyState from '../ui/EmptyState';
import { useTranslation } from 'react-i18next';
import { RefreshCw, BarChart3, Layers, CheckSquare } from 'lucide-react';
import Badge from '../ui/Badge';
import Row from './LeaderboardRow';
import { useSaveManualPoints } from '../../hooks/useLeaderboardMutations';

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

  const savePointsMutation = useSaveManualPoints();

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
      await savePointsMutation.mutateAsync({
        challengeId: challenge.id,
        user_id: scoringUser.id,
        points: { [scoringTask.id]: pts },
        reason: scoringReason.trim() || undefined,
      });

      showToast(
        t('leaderboard.save_points_success', {
          pts,
          name: scoringUser.name || scoringUser.username || scoringUser.alias_id,
        }),
      );
      setScoringModalOpen(false);
      if (onRefresh) onRefresh();
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

  // Renumber ranks sequentially after baseline removal. Backend provides correct ranks.
  let rankAcc = 0;
  displayData = displayData.map((entry) => {
    if (entry.has_submitted && entry.rank != null) {
      return { ...entry, rank: ++rankAcc };
    }
    return { ...entry, rank: null };
  });

  if (isStageTab) {
    displayData = displayData.map((entry) => ({
      ...entry,
      rank: entry.stage_ranks?.[activeTab] ?? null,
    }));
    displayData.sort((a, b) => {
      if (a.rank != null && b.rank != null) return a.rank - b.rank;
      if (a.rank != null) return -1;
      if (b.rank != null) return 1;
      return 0;
    });
  } else if (activeTab !== 'general') {
    const activeTaskIdStr = activeTab.toString();
    displayData = displayData.map((entry) => ({
      ...entry,
      rank: entry.task_ranks?.[activeTaskIdStr] ?? null,
    }));
    displayData.sort((a, b) => {
      if (a.rank != null && b.rank != null) return a.rank - b.rank;
      if (a.rank != null) return -1;
      if (b.rank != null) return 1;
      return 0;
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
                  const key = entry.user?.id ?? `row-${entry.rank}`;
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
            <Button
              variant="primary"
              onClick={handleSavePointsSubmit}
              disabled={savePointsMutation.isPending}
              isLoading={savePointsMutation.isPending}
            >
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
