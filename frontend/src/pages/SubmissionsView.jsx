import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import api from '../services/ApiService';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { useAuth } from '../AuthContext';
import TaskService from '../services/TaskService';
import SubmissionViewer from '../components/submissions/SubmissionViewer';
import Badge from '../components/ui/Badge';
import Pagination from '../components/ui/Pagination';
import EmptyState from '../components/ui/EmptyState';
import { formatLocalizedDate } from '../utils/formatDate';
import { Star, Download, ChevronRight, Search, X } from 'lucide-react';

function BestSubmissionCard({ sub, task, onView, onDownload, showPrivate, challenge }) {
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

function StageGroup({ stage, tasks, challenge, bestSubs, onView, onDownload, showPrivate }) {
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
          if (!sub) return null;
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
        })}
      </div>
    </div>
  );
}

export default function SubmissionsView() {
  const { t } = useTranslation();
  const { challengeId } = useParams();
  const { currentUser } = useAuth();
  const { selectedChallenge, setSelectedChallengeById, selectedTask, setSelectedTask, confirm } =
    useApp();

  const [submissions, setSubmissions] = useState([]);
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectingFinal, setSelectingFinal] = useState(false);

  const [submissionsPage, setSubmissionsPage] = useState(1);
  const [submissionsPages, setSubmissionsPages] = useState(1);
  const [submissionsTotal, setSubmissionsTotal] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const taskIdRef = useRef(selectedTask?.id);

  const isCompetitor = currentUser?.role === 'competitor';
  const isAdminOrJury = !isCompetitor;

  const [competitorSearch, setCompetitorSearch] = useState('');
  const [competitorResults, setCompetitorResults] = useState([]);
  const [competitorPage, setCompetitorPage] = useState(1);
  const [competitorPages, setCompetitorPages] = useState(1);
  const [competitorTotal, setCompetitorTotal] = useState(0);
  const [selectedCompetitor, setSelectedCompetitor] = useState(null);
  const [searching, setSearching] = useState(false);

  const [adminActiveTask, setAdminActiveTask] = useState(null);
  const [adminSubmissions, setAdminSubmissions] = useState([]);
  const [adminSubPage, setAdminSubPage] = useState(1);
  const [adminSubPages, setAdminSubPages] = useState(1);
  const [adminSubTotal, setAdminSubTotal] = useState(0);
  const [adminLoading, setAdminLoading] = useState(false);

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

  const fetchSubmissions = async (silent = false, pageToFetch = submissionsPage) => {
    if (!selectedTask) {
      setSubmissions([]);
      return;
    }
    if (!silent) setLoading(true);
    try {
      const res = await TaskService.getSubmissions(selectedTask.id, pageToFetch, 10);
      if (res.ok) {
        const data = res.data;
        if (data && data.items !== undefined) {
          setSubmissions(data.items || []);
          setSubmissionsTotal(data.total || 0);
          setSubmissionsPages(data.pages || 1);
          setSelectedSubmission((prev) => {
            if (!prev) return null;
            const updated = data.items.find((s) => s.id === prev.id);
            return updated ? { ...prev, ...updated } : prev;
          });
        } else {
          const arr = data || [];
          setSubmissions(arr);
          setSubmissionsTotal(arr.length);
          setSubmissionsPages(1);
          setSelectedSubmission((prev) => {
            if (!prev) return null;
            const updated = arr.find((s) => s.id === prev.id);
            return updated ? { ...prev, ...updated } : prev;
          });
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    setSubmissionsPage(1);
  }, [selectedTask]);

  useEffect(() => {
    if (!selectedTask) {
      setSubmissions([]);
      return;
    }
    setLoading(true);
    const taskId = selectedTask.id;
    const page = submissionsPage;
    const sseUrl = `/api/tasks/${taskId}/submissions/live?page=${page}&per_page=10`;
    const eventSource = new EventSource(sseUrl);
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data) {
          if (data.items !== undefined) {
            setSubmissions(data.items || []);
            setSubmissionsTotal(data.total || 0);
            setSubmissionsPages(data.pages || 1);
            setSelectedSubmission((prev) => {
              if (!prev) return null;
              const updated = data.items.find((s) => s.id === prev.id);
              return updated ? { ...prev, ...updated } : prev;
            });
          } else {
            const arr = data || [];
            setSubmissions(arr);
            setSubmissionsTotal(arr.length);
            setSubmissionsPages(1);
            setSelectedSubmission((prev) => {
              if (!prev) return null;
              const updated = arr.find((s) => s.id === prev.id);
              return updated ? { ...prev, ...updated } : prev;
            });
          }
        }
        setLoading(false);
      } catch (err) {
        console.error('Failed to parse submissions SSE data:', err);
      }
    };
    eventSource.onerror = () => {
      eventSource.close();
      const loadFallback = async () => {
        try {
          const res = await api.fetch(`/api/tasks/${taskId}/submissions?page=${page}&per_page=10`, {
            headers: {},
          });
          if (res.ok) {
            if (taskIdRef.current !== taskId) return;
            const d = await res.json();
            if (d && d.items !== undefined) {
              setSubmissions(d.items || []);
              setSubmissionsTotal(d.total || 0);
              setSubmissionsPages(d.pages || 1);
            } else {
              const arr = d || [];
              setSubmissions(arr);
              setSubmissionsTotal(arr.length);
              setSubmissionsPages(1);
            }
          }
        } catch (fetchErr) {
          console.error('Fallback fetch failed:', fetchErr);
        } finally {
          setLoading(false);
        }
      };
      loadFallback();
    };
    return () => eventSource.close();
  }, [selectedTask, submissionsPage]);

  const handleSelectFinal = async (submissionId) => {
    setSelectingFinal(true);
    try {
      const res = await api.fetch(`/api/submissions/${submissionId}/select-final`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (res.ok) {
        fetchSubmissions(true);
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

  const handleSelectSubmission = async (sub) => {
    if (!sub) {
      setSelectedSubmission(null);
      return;
    }
    setSelectedSubmission(sub);
    try {
      const res = await TaskService.getSubmissionDetail(sub.id);
      if (res.ok)
        setSelectedSubmission((prev) =>
          prev && prev.id === sub.id ? { ...prev, ...res.data } : prev,
        );
    } catch (err) {
      console.error(err);
    }
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

  // Admin: competitor search
  const handleSearchCompetitors = useCallback(
    async (search, pageNum = 1) => {
      if (!selectedChallenge) return;
      setSearching(true);
      try {
        const params = new URLSearchParams({
          role: 'competitor',
          challenge_id: String(selectedChallenge.id),
          page: String(pageNum),
          per_page: '10',
        });
        if (search) params.set('search', search);
        const res = await api.get(`/admin/users?${params.toString()}`);
        if (res.ok && res.data) {
          setCompetitorResults(res.data.items || []);
          setCompetitorPage(res.data.page || 1);
          setCompetitorPages(res.data.pages || 1);
          setCompetitorTotal(res.data.total || 0);
        }
      } catch (err) {
        console.error('Competitor search failed:', err);
      } finally {
        setSearching(false);
      }
    },
    [selectedChallenge],
  );

  useEffect(() => {
    if (isAdminOrJury && selectedChallenge) handleSearchCompetitors('', 1);
  }, [isAdminOrJury, selectedChallenge, handleSearchCompetitors]);

  const handleSelectCompetitor = (competitor) => {
    setSelectedCompetitor(competitor);
    setAdminActiveTask(null);
    setAdminSubmissions([]);
    setSelectedSubmission(null);
    setCompetitorSearch('');
    setCompetitorResults([]);
    const tasks = selectedChallenge?.tasks || [];
    const firstTask = tasks[0];
    if (firstTask) {
      setAdminActiveTask(firstTask.id);
      setAdminSubPage(1);
      (async () => {
        try {
          const res = await api.fetch(
            `/api/tasks/${firstTask.id}/submissions?page=1&per_page=10&user_id=${competitor.id}`,
          );
          if (res.ok) {
            const data = await res.json();
            setAdminSubmissions(data.items || []);
            setAdminSubPages(data.pages || 1);
            setAdminSubTotal(data.total || 0);
          }
        } catch (err) {
          console.error('Failed to fetch admin task submissions:', err);
        }
      })();
    }
  };

  // Admin: fetch best submissions across all tasks for the selected competitor
  const fetchAllCompetitorSubmissions = useCallback(async () => {
    if (!selectedChallenge || !selectedCompetitor) return;
    const tasks = selectedChallenge.tasks || [];
    const bestPerTask = {};
    for (const task of tasks) {
      try {
        const res = await TaskService.getSubmissions(task.id, 1, 100);
        if (res.ok) {
          const data = res.data;
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
      const activeId = adminActiveTask;
      if (activeId && result[activeId]) {
        const sub = result[activeId];
        setSelectedSubmission(sub);
        TaskService.getSubmissionDetail(sub.id).then((res) => {
          if (res.ok && !cancelled)
            setSelectedSubmission((prev) =>
              prev && prev.id === sub.id ? { ...prev, ...res.data } : prev,
            );
        });
      } else if (!activeId) {
        const firstTaskId = Object.keys(result)[0];
        if (firstTaskId) {
          setAdminActiveTask(firstTaskId);
          setAdminSubPage(1);
          const sub = result[firstTaskId];
          setSelectedSubmission(sub);
          TaskService.getSubmissionDetail(sub.id).then((res) => {
            if (res.ok && !cancelled)
              setSelectedSubmission((prev) =>
                prev && prev.id === sub.id ? { ...prev, ...res.data } : prev,
              );
          });
          (async () => {
            const res = await api.fetch(
              `/api/tasks/${firstTaskId}/submissions?page=1&per_page=10&user_id=${selectedCompetitor.id}`,
            );
            if (res.ok) {
              const data = await res.json();
              if (!cancelled) {
                setAdminSubmissions(data.items || []);
                setAdminSubPages(data.pages || 1);
                setAdminSubTotal(data.total || 0);
              }
            }
          })();
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedCompetitor, selectedChallenge, isAdminOrJury, fetchAllCompetitorSubmissions]);

  // Admin: fetch all submissions for a specific task for the selected competitor
  const fetchAdminTaskSubmissions = useCallback(
    async (taskId, pageNum = 1) => {
      if (!selectedCompetitor) return;
      setAdminLoading(true);
      try {
        const res = await api.fetch(
          `/api/tasks/${taskId}/submissions?page=${pageNum}&per_page=10&user_id=${selectedCompetitor.id}`,
        );
        if (res.ok) {
          const data = await res.json();
          if (data) {
            setAdminSubmissions(data.items || []);
            setAdminSubPages(data.pages || 1);
            setAdminSubTotal(data.total || 0);
          }
        }
      } catch (err) {
        console.error('Failed to fetch admin task submissions:', err);
      } finally {
        setAdminLoading(false);
      }
    },
    [selectedCompetitor],
  );

  const handleAdminViewSubmission = async (sub) => {
    if (!sub) {
      setSelectedSubmission(null);
      return;
    }
    setSelectedSubmission(sub);
    try {
      const res = await TaskService.getSubmissionDetail(sub.id);
      if (res.ok)
        setSelectedSubmission((prev) =>
          prev && prev.id === sub.id ? { ...prev, ...res.data } : prev,
        );
    } catch (err) {
      console.error(err);
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
      }
    } catch (err) {
      console.error('Download failed:', err);
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

  // Student view
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
        <div className="surface" style={{ padding: '20px' }}>
          <div className="text-sm font-bold text-slate-200 mb-3">
            {t('submissions.select_competitor', 'Select Competitor')}
          </div>
          <div className="relative mb-3">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={competitorSearch}
              onChange={(e) => {
                setCompetitorSearch(e.target.value);
                handleSearchCompetitors(e.target.value, 1);
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
                onPageChange={(p) => handleSearchCompetitors(competitorSearch, p)}
                itemName={t('submissions.pagination_item_name')}
              />
            </div>
          )}
        </div>
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
                handleSearchCompetitors('', 1);
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
            {groupedByStage.map(({ stage, tasks }) => {
              const hasSubs = tasks.some((t) => bestSubs[t.id]);
              if (!hasSubs) return null;
              return (
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
                />
              );
            })}
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
                    fetchAdminTaskSubmissions(adminActiveTask, p);
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
            />
          )}
        </>
      )}
    </div>
  );
}
