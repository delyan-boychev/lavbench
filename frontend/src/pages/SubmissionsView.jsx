import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { useAuth } from '../AuthContext';
import useSSE from '../hooks/useSSE';
import { useApiError } from '../hooks/useApiError';
import TaskService from '../services/TaskService';
import { useSubmissionsQuery } from '../hooks/useSubmissionsQuery';
import { useSubmissionDetailQuery } from '../hooks/useSubmissionDetailQuery';
import { useCompetitorSearchQuery } from '../hooks/useCompetitorSearchQuery';
import SubmissionViewer from '../components/submissions/SubmissionViewer';
import Badge from '../components/ui/Badge';
import Pagination from '../components/ui/Pagination';
import EmptyState from '../components/ui/EmptyState';
import BestSubmissionCard from '../components/submissions/BestSubmissionCard';
import StageGroup from '../components/submissions/StageGroup';
import { formatLocalizedDate } from '../utils/formatDate';
import { Star, Download, ChevronRight, Search, X } from 'lucide-react';

export default function SubmissionsView() {
  const { t } = useTranslation();
  const { challengeId } = useParams();
  const { currentUser } = useAuth();
  const {
    selectedChallenge,
    setSelectedChallengeById,
    selectedTask,
    setSelectedTask,
    confirm,
    showToast,
  } = useApp();
  const { showApiError } = useApiError();

  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [selectingFinal, setSelectingFinal] = useState(false);
  const [killing, setKilling] = useState(false);

  const [submissionsPage, setSubmissionsPage] = useState(1);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const taskIdRef = useRef(selectedTask?.id);

  const isCompetitor = currentUser?.role === 'competitor';
  const isAdminOrJury = !isCompetitor;

  const [competitorSearch, setCompetitorSearch] = useState('');
  const [competitorPage, setCompetitorPage] = useState(1);
  const [selectedCompetitor, setSelectedCompetitor] = useState(null);

  const [adminActiveTask, setAdminActiveTask] = useState(null);
  const adminActiveTaskRef = useRef(adminActiveTask);
  useEffect(() => {
    adminActiveTaskRef.current = adminActiveTask;
  }, [adminActiveTask]);
  const [adminSubPage, setAdminSubPage] = useState(1);

  const [baselineExpanded, setBaselineExpanded] = useState(false);

  const queryClient = useQueryClient();

  const { data: subsData, isLoading: loading } = useSubmissionsQuery(
    selectedTask?.id,
    submissionsPage,
    10,
  );
  const submissions = subsData?.items || [];
  const submissionsPages = subsData?.pages || 1;
  const submissionsTotal = subsData?.total || 0;

  const { data: competitorData, isLoading: searching } = useCompetitorSearchQuery(
    selectedChallenge?.id,
    competitorSearch,
    competitorPage,
  );
  const competitorResults = competitorData?.items || [];
  const competitorPages = competitorData?.pages || 1;
  const competitorTotal = competitorData?.total || 0;

  const { data: adminSubsData, isLoading: adminLoading } = useQuery({
    queryKey: ['admin-submissions', adminActiveTask, adminSubPage, selectedCompetitor?.id],
    queryFn: async () => {
      const res = await api.fetch(
        `/api/tasks/${adminActiveTask}/submissions?page=${adminSubPage}&per_page=10&user_id=${selectedCompetitor.id}`,
      );
      if (!res.ok) throw new Error('Failed to load admin submissions');
      return res.json();
    },
    enabled: !!adminActiveTask && !!selectedCompetitor,
    staleTime: 10_000,
  });
  const adminSubmissions = adminSubsData?.items || [];
  const adminSubPages = adminSubsData?.pages || 1;
  const adminSubTotal = adminSubsData?.total || 0;

  const { data: baselineSubmissions = [], isLoading: baselineLoading } = useQuery({
    queryKey: ['baselines', selectedChallenge?.id],
    queryFn: async () => {
      const tasks = selectedChallenge?.tasks || [];
      const results = await Promise.all(
        tasks.map(async (task) => {
          try {
            const res = await api.fetch(
              `/api/tasks/${task.id}/submissions?baseline=true&page=1&per_page=100`,
            );
            if (res.ok) {
              const data = await res.json();
              const items = data?.items || data || [];
              return items.length > 0 ? { task, submission: items[0] } : null;
            }
          } catch {
            // ignore per-task errors
          }
          return null;
        }),
      );
      return results.filter(Boolean);
    },
    enabled: baselineExpanded,
    staleTime: 30_000,
  });

  const { data: submissionDetail } = useSubmissionDetailQuery(selectedSubmission?.id);
  useEffect(() => {
    if (submissionDetail && selectedSubmission) {
      setSelectedSubmission((prev) =>
        prev && prev.id === submissionDetail.id ? { ...prev, ...submissionDetail } : prev,
      );
    }
  }, [submissionDetail, selectedSubmission?.id]);

  const handleSubmissionUpdate = useCallback(
    (updated) => {
      setSelectedSubmission((prev) =>
        prev && prev.id === updated.id ? { ...prev, ...updated } : prev,
      );
      queryClient.invalidateQueries({ queryKey: ['submissions'] });
      queryClient.invalidateQueries({ queryKey: ['admin-submissions'] });
      queryClient.invalidateQueries({ queryKey: ['baselines'] });
    },
    [queryClient],
  );

  useEffect(() => {
    taskIdRef.current = selectedTask?.id;
  }, [selectedTask]);

  useEffect(() => {
    if (challengeId) setSelectedChallengeById(challengeId);
  }, [challengeId, setSelectedChallengeById]);

  useEffect(() => {
    if (selectedChallenge?.tasks?.length > 0 && !selectedTask) {
      setSelectedTask(selectedChallenge.tasks[0]);
    }
  }, [selectedChallenge, selectedTask, setSelectedTask]);

  useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    setSubmissionsPage(1);
  }, [selectedTask]);

  useEffect(() => {
    setCompetitorPage(1);
  }, [competitorSearch]);

  const taskId = selectedTask?.id;
  const page = submissionsPage;

  useSSE(taskId ? `/api/tasks/${taskId}/submissions/live?page=${page}&per_page=10` : '', {
    onMessage: () => {
      queryClient.invalidateQueries({ queryKey: ['submissions'] });
    },
    onError: () => {},
  });

  const handleSelectFinal = async (submissionId) => {
    setSelectingFinal(true);
    try {
      const res = await api.fetch(`/api/submissions/${submissionId}/select-final`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (res.ok) {
        setSelectedSubmission((prev) => (prev ? { ...prev, is_final_selection: true } : prev));
        await queryClient.invalidateQueries({ queryKey: ['submissions'] });
      } else {
        const errData = await res.json();
        await confirm({
          title: t('submissions.selection_error'),
          message: errData.code
            ? t(`api.${errData.code}`, errData.error || t('submissions.select_final_failed'))
            : errData.error || t('submissions.select_final_failed'),
          confirmText: t('common.ok'),
          cancelText: '',
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setSelectingFinal(false);
    }
  };

  const handleKillSubmission = async (submissionId) => {
    const confirmed = await confirm(t('submissions.kill_confirm'), t('submissions.kill'));
    if (!confirmed) return;

    setKilling(true);
    try {
      const res = await TaskService.killSubmission(submissionId);
      if (res.ok) {
        showToast(t('submissions.kill_success'), 'emerald');
        setSelectedSubmission((prev) =>
          prev && prev.id === submissionId
            ? { ...prev, status: 'failed', detailed_status: 'killed' }
            : prev,
        );
        await queryClient.invalidateQueries({ queryKey: ['submissions'] });
      } else {
        showApiError(res.data, 'submissions.kill_failed');
      }
    } catch (err) {
      console.error(err);
      showApiError(err, 'submissions.kill_failed');
    } finally {
      setKilling(false);
    }
  };

  const handleSelectSubmission = (sub) => {
    if (!sub) {
      setSelectedSubmission(null);
      return;
    }
    setSelectedSubmission(sub);
  };

  const stage = selectedChallenge?.stages?.find((s) => s.id === selectedTask?.stage_id);
  let finalSelectDeadline = null;
  let hasRunningPreDeadline = false;
  if (stage) {
    const stageEndTimeMs = new Date(stage.end_time).getTime();
    finalSelectDeadline = stageEndTimeMs + 300000;
    if (submissions && submissions.length > 0) {
      for (const sub of submissions) {
        const createdAtMs = new Date(sub.created_at).getTime();
        if (createdAtMs <= stageEndTimeMs) {
          if (sub.executed_at) {
            const executedAtMs = new Date(sub.executed_at).getTime();
            const tSelect = executedAtMs + 300000;
            if (tSelect > finalSelectDeadline) finalSelectDeadline = tSelect;
          } else if (sub.status === 'queued' || sub.status === 'running') {
            hasRunningPreDeadline = true;
          }
        }
      }
    }
  }
  const isSelectionDisabled = stage
    ? !hasRunningPreDeadline && finalSelectDeadline !== null && nowMs > finalSelectDeadline
    : false;
  const isSubmissionAfterDeadline =
    stage && selectedSubmission
      ? new Date(selectedSubmission.created_at).getTime() > new Date(stage.end_time).getTime()
      : false;

  const bestSubmission = useMemo(() => {
    if (!submissions.length) return null;
    const final = submissions.find((s) => s.is_final_selection);
    if (final) return final;
    return submissions.reduce(
      (best, s) =>
        s.public_score != null && (!best || s.public_score > best.public_score) ? s : best,
      null,
    );
  }, [submissions]);

  const handleSelectCompetitor = (competitor) => {
    setSelectedCompetitor(competitor);
    setBaselineExpanded(false);
    setAdminActiveTask(null);
    setSelectedSubmission(null);
    setCompetitorSearch('');
    const tasks = selectedChallenge?.tasks || [];
    const firstTask = tasks[0];
    if (firstTask) {
      setAdminActiveTask(firstTask.id);
      setAdminSubPage(1);
    }
  };

  // Admin: fetch best submissions across all tasks for the selected competitor
  const fetchAllCompetitorSubmissions = useCallback(async () => {
    if (!selectedChallenge || !selectedCompetitor) return {};
    const tasks = selectedChallenge.tasks || [];
    const bestPerTask = {};
    for (const task of tasks) {
      try {
        const res = await api.fetch(`/api/tasks/${task.id}/submissions?page=1&per_page=100`);
        if (res.ok) {
          const data = await res.json();
          const items = data?.items || data || [];
          const userSubs = items.filter((s) => s.user?.id === selectedCompetitor.id);
          if (userSubs.length === 0) continue;
          const final = userSubs.find((s) => s.is_final_selection);
          if (final) {
            bestPerTask[task.id] = final;
            continue;
          }
          const best = userSubs.reduce(
            (b, s) => (s.public_score != null && (!b || s.public_score > b.public_score) ? s : b),
            null,
          );
          if (best) bestPerTask[task.id] = best;
        }
      } catch (err) {
        console.error(`Failed to fetch submissions for task ${task.id}:`, err);
      }
    }
    return bestPerTask;
  }, [selectedChallenge, selectedCompetitor]);

  const [bestSubs, setBestSubs] = useState({});

  useEffect(() => {
    if (!isAdminOrJury || !selectedCompetitor || !selectedChallenge) {
      setBestSubs({});
      return;
    }
    let cancelled = false;
    fetchAllCompetitorSubmissions().then((result) => {
      if (cancelled) return;
      setBestSubs(result);
      const activeId = adminActiveTaskRef.current;
      const resolvedTaskId = activeId && result[activeId] ? activeId : Object.keys(result)[0];
      if (resolvedTaskId) {
        if (resolvedTaskId !== activeId) {
          setAdminActiveTask(resolvedTaskId);
          setAdminSubPage(1);
        }
        const sub = result[resolvedTaskId];
        if (sub) {
          setSelectedSubmission(sub);
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedCompetitor, selectedChallenge, isAdminOrJury, fetchAllCompetitorSubmissions]);

  const handleAdminViewSubmission = (sub) => {
    if (!sub) {
      setSelectedSubmission(null);
      return;
    }
    setSelectedSubmission(sub);
    if (sub.task_id) {
      const taskChanged = sub.task_id !== adminActiveTask;
      setAdminActiveTask(sub.task_id);
      if (taskChanged) {
        setAdminSubPage(1);
      }
    }
  };

  const handleDownloadSubmission = async (taskId, userId) => {
    if (!selectedChallenge) return;
    try {
      const res = await api.fetch(
        `/challenges/${selectedChallenge.id}/tasks/${taskId}/users/${userId}/download`,
      );
      if (res.ok) {
        const blob = await res.blob();
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.download = `submission_${taskId}_${userId}.ipynb`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } else {
        showToast(t('submissions.download_failed', 'Download failed'), 'rose');
      }
    } catch {
      showToast(t('submissions.download_error', 'Error downloading submission'), 'rose');
    }
  };

  const groupedByStage = useMemo(() => {
    if (!selectedChallenge || !selectedChallenge.stages || selectedChallenge.stages.length === 0) {
      const tasks = selectedChallenge?.tasks || [];
      return [{ stage: null, tasks }];
    }
    const stages = [...selectedChallenge.stages].sort((a, b) => a.stage_number - b.stage_number);
    const result = [];
    for (const stage of stages) {
      const stageTasks = (selectedChallenge.tasks || []).filter((t) => t.stage_id === stage.id);
      result.push({ stage, tasks: stageTasks });
    }
    const noStageTasks = (selectedChallenge.tasks || []).filter((t) => !t.stage_id);
    if (noStageTasks.length > 0) result.push({ stage: null, tasks: noStageTasks });
    return result;
  }, [selectedChallenge]);

  const renderTimer = () => {
    if (!stage) return null;
    let timerText = '';
    let isExpired = false;
    if (hasRunningPreDeadline) timerText = t('submissions.waiting_for_evaluation');
    else if (finalSelectDeadline) {
      const diff = finalSelectDeadline - nowMs;
      if (diff <= 0) {
        timerText = t('submissions.selection_closed');
        isExpired = true;
      } else {
        const totalSecs = Math.ceil(diff / 1000);
        const hours = Math.floor(totalSecs / 3600);
        const min = Math.floor((totalSecs % 3600) / 60);
        const sec = totalSecs % 60;
        timerText = t('submissions.time_remaining_select_final', {
          time:
            hours > 0
              ? `${hours.toString().padStart(2, '0')}:${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
              : `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`,
        });
      }
    }
    return (
      <div
        style={{
          fontSize: '0.8rem',
          fontWeight: 600,
          color: isExpired ? 'var(--danger)' : 'var(--warning)',
          background: isExpired ? 'rgba(239, 68, 68, 0.1)' : 'rgba(245, 158, 11, 0.1)',
          border: `1px solid ${isExpired ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.2)'}`,
          borderRadius: 'var(--radius-md)',
          padding: '10px 14px',
          textAlign: 'center',
        }}
      >
        {timerText}
      </div>
    );
  };

  if (!selectedChallenge)
    return <EmptyState message={t('submissions.no_competition_selected')} minHeight={200} />;

  // Competitor view
  if (isCompetitor) {
    const tasks = selectedChallenge.tasks || [];
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
        {tasks.length > 1 && (
          <div
            className="surface"
            style={{ padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12 }}
          >
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {t('submissions.select_task')}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="flex gap-1.5 overflow-x-auto no-scrollbar">
                {tasks.map((task) => (
                  <button
                    key={task.id}
                    onClick={() => {
                      setSelectedTask(task);
                      setSelectedSubmission(null);
                    }}
                    className={`nav-tab flex-shrink-0 ${selectedTask?.id === task.id ? 'active' : ''}`}
                    style={{ padding: '4px 12px', fontSize: '0.75rem' }}
                  >
                    {task.title}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {selectedTask ? (
          <div key={selectedTask.id} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {renderTimer()}

            {bestSubmission && (
              <div className="flex flex-col gap-1.5">
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider px-1">
                  {t('submissions.best_submission', 'Best Submission')}
                </div>
                <BestSubmissionCard
                  sub={bestSubmission}
                  task={selectedTask}
                  onView={handleSelectSubmission}
                  onDownload={undefined}
                  showPrivate={false}
                  challenge={selectedChallenge}
                />
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="flex flex-col gap-2">
                <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1 px-1">
                  {t('submissions.title_with_count', {
                    count: submissionsTotal || submissions.length,
                  })}
                </div>
                <div className="flex flex-col gap-1.5">
                  {loading && submissions.length === 0 ? (
                    <EmptyState minHeight={200} message={t('submissions.loading')}>
                      <div className="animate-spin w-5.5 h-5.5 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
                    </EmptyState>
                  ) : submissions.length === 0 ? (
                    <EmptyState minHeight={200} message={t('submissions.none_found')} />
                  ) : (
                    submissions.map((sub) => {
                      const isSel = selectedSubmission?.id === sub.id;
                      return (
                        <button
                          key={sub.id}
                          onClick={() => handleSelectSubmission(sub)}
                          className={`flex flex-col gap-1.5 p-3 rounded-lg text-left w-full transition-all duration-150 border cursor-pointer ${
                            isSel
                              ? 'bg-indigo-500/10 border-indigo-500/40 text-slate-100'
                              : sub.is_final_selection
                                ? 'bg-slate-900/40 border-indigo-500/25 hover:bg-slate-800/60 text-slate-300'
                                : 'bg-slate-900/40 border-slate-800 hover:bg-slate-800/60 text-slate-300'
                          }`}
                        >
                          <div className="flex justify-between items-center gap-2 w-full">
                            <span className="font-mono text-xs text-slate-500 flex items-center gap-1">
                              #{sub.id}
                              {sub.is_final_selection && (
                                <span className="flex items-center gap-0.5 text-indigo-400 text-[10px] font-bold">
                                  <Star className="w-3 h-3" />
                                  {t('submissions.final_selection_label')}
                                </span>
                              )}
                            </span>
                            <Badge status={sub.status} />
                          </div>
                          <div className="flex justify-between items-center gap-2 w-full">
                            <span className="text-xs text-slate-400">
                              {sub.created_at
                                ? `${formatLocalizedDate(sub.created_at, { timeZone: selectedChallenge.timezone || 'UTC' })}`
                                : '—'}
                            </span>
                            {sub.public_score != null && (
                              <span className="font-mono text-xs font-bold text-indigo-400">
                                {Number(sub.public_score).toFixed(4)}
                              </span>
                            )}
                          </div>
                          {sub.user?.alias_id && (
                            <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                              {t('submissions.alias', { alias: sub.user.alias_id })}
                            </div>
                          )}
                        </button>
                      );
                    })
                  )}
                </div>
                <div className="mt-2">
                  <Pagination
                    page={submissionsPage}
                    pages={submissionsPages}
                    total={submissionsTotal}
                    perPage={10}
                    onPageChange={setSubmissionsPage}
                    itemName={t('submissions.pagination_item_name')}
                  />
                </div>
              </div>
              <SubmissionViewer
                submission={selectedSubmission}
                currentUser={currentUser}
                onSelectFinal={handleSelectFinal}
                selectingFinal={selectingFinal}
                isSelectionDisabled={isSelectionDisabled || isSubmissionAfterDeadline}
                isSubmissionAfterDeadline={isSubmissionAfterDeadline}
                onSubmissionUpdate={handleSubmissionUpdate}
                onKill={handleKillSubmission}
                killing={killing}
              />
            </div>
          </div>
        ) : (
          <EmptyState message={t('submissions.no_task_selected')} minHeight={200} />
        )}
      </div>
    );
  }

  // Admin/Jury view
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {/* Competitor Search */}
      {!selectedCompetitor ? (
        <>
          {/* Baseline Submissions */}
          {(selectedChallenge?.tasks?.length ?? 0) > 0 && (
            <div className="surface" style={{ padding: '16px 20px' }}>
              <button
                onClick={() => {
                  if (baselineExpanded) {
                    setSelectedSubmission(null);
                  }
                  setBaselineExpanded(!baselineExpanded);
                }}
                className="flex items-center justify-between w-full text-left"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-200">
                    {t('submissions.baseline_submissions', 'Baseline Solutions')}
                  </span>
                  {!baselineExpanded && baselineSubmissions.length > 0 && (
                    <span className="text-[10px] text-slate-500 font-semibold">
                      {baselineSubmissions.length} {t('submissions.task_count', 'tasks')}
                    </span>
                  )}
                </div>
                <ChevronRight
                  size={14}
                  className={`transition-transform ${baselineExpanded ? 'rotate-90' : ''} text-slate-400`}
                />
              </button>
              {baselineExpanded && (
                <div className="mt-4 flex flex-col gap-1.5">
                  {baselineLoading ? (
                    <div className="flex items-center justify-center py-6">
                      <div className="animate-spin w-5 h-5 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
                    </div>
                  ) : baselineSubmissions.length === 0 ? (
                    <div className="text-xs text-slate-500 text-center py-4">
                      {t('submissions.no_baselines', 'No baseline submissions available')}
                    </div>
                  ) : (
                    baselineSubmissions.map(({ task, submission: sub }) => {
                      const isSel = selectedSubmission?.id === sub.id;
                      return (
                        <button
                          key={task.id}
                          onClick={() => handleAdminViewSubmission(sub)}
                          className={`flex flex-col gap-1.5 p-3 rounded-lg text-left w-full transition-all duration-150 border cursor-pointer ${
                            isSel
                              ? 'bg-indigo-500/10 border-indigo-500/40 text-slate-100'
                              : 'bg-slate-900/40 border-slate-800 hover:bg-slate-800/60 text-slate-300'
                          }`}
                        >
                          <div className="flex justify-between items-center gap-2 w-full">
                            <span className="text-sm font-semibold text-slate-200 truncate">
                              {task.title}
                            </span>
                            <Badge status={sub.status} />
                          </div>
                          <div className="flex justify-between items-center gap-2 w-full">
                            <span className="font-mono text-xs text-slate-500">
                              #{sub.id}
                              {sub.created_at && (
                                <span className="ml-2 text-slate-400 font-sans">
                                  {formatLocalizedDate(sub.created_at, {
                                    timeZone: selectedChallenge?.timezone || 'UTC',
                                  })}
                                </span>
                              )}
                            </span>
                            {sub.public_score != null && (
                              <span className="font-mono text-xs font-bold text-indigo-400">
                                {Number(sub.public_score).toFixed(4)}
                              </span>
                            )}
                          </div>
                        </button>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          )}

          {/* SubmissionViewer for selected baseline */}
          {selectedSubmission && !selectedCompetitor && (
            <SubmissionViewer
              submission={selectedSubmission}
              currentUser={currentUser}
              onSelectFinal={() => {}}
              onSubmissionUpdate={handleSubmissionUpdate}
              onKill={handleKillSubmission}
              killing={killing}
            />
          )}

          <div className="surface" style={{ padding: '20px' }}>
            <div className="text-sm font-bold text-slate-200 mb-3">
              {t('submissions.select_competitor', 'Select Competitor')}
            </div>
            <div className="relative mb-3">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
              />
              <input
                type="text"
                value={competitorSearch}
                onChange={(e) => {
                  setCompetitorSearch(e.target.value);
                }}
                placeholder={t(
                  'submissions.search_competitor_placeholder',
                  'Search by alias, name, or school...',
                )}
                className="w-full pl-9 pr-3 py-2 bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 rounded-lg text-sm text-slate-200"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              {searching ? (
                <EmptyState minHeight={100} message={t('common.searching')} />
              ) : competitorResults.length === 0 ? (
                <div className="text-xs text-slate-500 text-center py-6">
                  {t('submissions.no_competitors_found', 'No competitors found')}
                </div>
              ) : (
                competitorResults.map((u) => (
                  <button
                    key={u.id}
                    onClick={() => handleSelectCompetitor(u)}
                    className="flex items-center justify-between p-3 rounded-lg bg-slate-900/40 border border-slate-800 hover:bg-slate-800/60 hover:border-indigo-500/30 transition-all cursor-pointer text-left"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-xs font-bold text-slate-400">
                        {(u.alias_id || '?')[0]}
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-slate-200">
                          {u.alias_id || u.username}
                        </div>
                        {u.name && (
                          <div className="text-xs text-slate-400">
                            {u.name} {u.surname}
                          </div>
                        )}
                        {u.school && <div className="text-[10px] text-slate-500">{u.school}</div>}
                      </div>
                    </div>
                    <ChevronRight size={14} className="text-slate-500" />
                  </button>
                ))
              )}
            </div>
            {competitorPages > 1 && (
              <div className="mt-3">
                <Pagination
                  page={competitorPage}
                  pages={competitorPages}
                  total={competitorTotal}
                  perPage={10}
                  onPageChange={(p) => setCompetitorPage(p)}
                  itemName={t('submissions.pagination_item_name')}
                />
              </div>
            )}
          </div>
        </>
      ) : (
        <>
          {/* Selected Competitor Header */}
          <div
            className="surface"
            style={{
              padding: '14px 20px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '10px',
            }}
          >
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-full bg-indigo-500/20 flex items-center justify-center text-sm font-bold text-indigo-400 flex-shrink-0">
                {(selectedCompetitor.alias_id || '?')[0].toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-bold text-slate-100 truncate">
                  {selectedCompetitor.alias_id || selectedCompetitor.username}
                </div>
                {selectedCompetitor.name && (
                  <div className="text-xs text-slate-400 truncate">
                    {selectedCompetitor.name} {selectedCompetitor.surname}
                  </div>
                )}
              </div>
            </div>
            <button
              onClick={() => {
                setCompetitorSearch('');
                setSelectedCompetitor(null);
                setAdminActiveTask(null);
                setBestSubs({});
                setSelectedSubmission(null);
              }}
              className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 hover:text-slate-100 bg-slate-800/60 hover:bg-slate-700/80 border border-slate-700 hover:border-slate-500 transition-all px-3 py-1.5 rounded-lg flex-shrink-0"
            >
              <X size={13} />
              {t('submissions.switch_competitor', 'Switch Competitor')}
            </button>
          </div>

          {/* Stage-grouped task cards */}
          <div className="flex flex-col gap-4">
            {groupedByStage.map(({ stage, tasks }) => (
              <StageGroup
                key={stage?.id || 'no-stage'}
                stage={stage}
                tasks={tasks}
                challenge={selectedChallenge}
                bestSubs={bestSubs}
                onView={handleAdminViewSubmission}
                onDownload={(sub) =>
                  handleDownloadSubmission(
                    adminActiveTask || sub.task_id,
                    sub.user?.id || selectedCompetitor.id,
                  )
                }
                showPrivate={true}
                onTaskClick={(taskId) => {
                  setAdminActiveTask(taskId);
                  setSelectedSubmission(null);
                  setAdminSubPage(1);
                }}
              />
            ))}
          </div>

          {/* All submissions for the active task */}
          {adminActiveTask && (
            <div className="surface" style={{ padding: '16px 20px' }}>
              <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-3">
                {t('submissions.title_with_count', {
                  count: adminSubTotal || adminSubmissions.length,
                })}
              </div>
              <div className="flex flex-col gap-1.5">
                {adminLoading && adminSubmissions.length === 0 ? (
                  <EmptyState minHeight={100} message={t('submissions.loading')}>
                    <div className="animate-spin w-5.5 h-5.5 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
                  </EmptyState>
                ) : adminSubmissions.length === 0 ? (
                  <div className="text-xs text-slate-500 text-center py-4">
                    {t('submissions.none_found')}
                  </div>
                ) : (
                  adminSubmissions.map((sub) => {
                    const isSel = selectedSubmission?.id === sub.id;
                    return (
                      <button
                        key={sub.id}
                        onClick={() => handleAdminViewSubmission(sub)}
                        className={`flex flex-col gap-1.5 p-3 rounded-lg text-left w-full transition-all duration-150 border cursor-pointer ${
                          isSel
                            ? 'bg-indigo-500/10 border-indigo-500/40 text-slate-100'
                            : sub.is_final_selection
                              ? 'bg-slate-900/40 border-indigo-500/25 hover:bg-slate-800/60 text-slate-300'
                              : 'bg-slate-900/40 border-slate-800 hover:bg-slate-800/60 text-slate-300'
                        }`}
                      >
                        <div className="flex justify-between items-center gap-2 w-full">
                          <span className="font-mono text-xs text-slate-500 flex items-center gap-1">
                            #{sub.id}
                            {sub.is_final_selection && (
                              <span className="flex items-center gap-0.5 text-indigo-400 text-[10px] font-bold">
                                <Star className="w-3 h-3" />
                                {t('submissions.final_selection_label')}
                              </span>
                            )}
                          </span>
                          <div className="flex items-center gap-2">
                            <Badge status={sub.status} />
                            <span
                              role="button"
                              tabIndex={0}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDownloadSubmission(
                                  adminActiveTask,
                                  sub.user?.id || selectedCompetitor.id,
                                );
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.stopPropagation();
                                  handleDownloadSubmission(
                                    adminActiveTask,
                                    sub.user?.id || selectedCompetitor.id,
                                  );
                                }
                              }}
                              className="p-1 rounded text-slate-500 hover:text-indigo-400 transition-colors cursor-pointer"
                              title={t('submissions.download')}
                            >
                              <Download size={12} />
                            </span>
                          </div>
                        </div>

                        <div className="flex justify-between items-center gap-2 w-full">
                          <span className="text-xs text-slate-400">
                            {sub.created_at
                              ? `${formatLocalizedDate(sub.created_at, { timeZone: selectedChallenge.timezone || 'UTC' })}`
                              : '—'}
                          </span>
                          <div className="flex items-center gap-3">
                            {sub.public_score != null && (
                              <span className="font-mono text-xs font-bold text-indigo-400">
                                <span className="text-[9px] text-slate-500 uppercase tracking-wider mr-1">
                                  {t('submissions.public_score')}:
                                </span>
                                {Number(sub.public_score).toFixed(4)}
                              </span>
                            )}
                            {sub.private_score != null && (
                              <span className="font-mono text-xs font-bold text-emerald-400">
                                <span className="text-[9px] text-slate-500 uppercase tracking-wider mr-1">
                                  {t('submissions.private_score')}:
                                </span>
                                {Number(sub.private_score).toFixed(4)}
                              </span>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
              <div className="mt-3">
                <Pagination
                  page={adminSubPage}
                  pages={adminSubPages}
                  total={adminSubTotal}
                  perPage={10}
                  onPageChange={(p) => {
                    setAdminSubPage(p);
                  }}
                  itemName={t('submissions.pagination_item_name')}
                />
              </div>
            </div>
          )}

          {/* Selected submission detail */}
          {selectedSubmission && (
            <SubmissionViewer
              submission={selectedSubmission}
              currentUser={currentUser}
              onSelectFinal={handleSelectFinal}
              selectingFinal={selectingFinal}
              isSelectionDisabled={isSelectionDisabled}
              isSubmissionAfterDeadline={isSubmissionAfterDeadline}
              onSubmissionUpdate={handleSubmissionUpdate}
              onKill={handleKillSubmission}
              killing={killing}
            />
          )}
        </>
      )}
    </div>
  );
}
