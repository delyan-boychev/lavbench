import React, { useState, useEffect } from 'react';
import api from '../services/ApiService';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { useAuth } from '../AuthContext';
import TaskService from '../services/TaskService';
import SubmissionList from '../components/submissions/SubmissionList';
import SubmissionViewer from '../components/submissions/SubmissionViewer';
import TabScrollContainer from '../components/ui/TabScrollContainer';
import EmptyState from '../components/ui/EmptyState';

export default function SubmissionsView() {
  const { t } = useTranslation();
  const { challengeId } = useParams();
  const { currentUser, token } = useAuth();
  const { 
    selectedChallenge, 
    setSelectedChallengeById, 
    selectedTask, 
    setSelectedTask,
    confirm
  } = useApp();

  const [submissions, setSubmissions] = useState([]);
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectingFinal, setSelectingFinal] = useState(false);

  const [submissionsPage, setSubmissionsPage] = useState(1);
  const [submissionsPages, setSubmissionsPages] = useState(1);
  const [submissionsTotal, setSubmissionsTotal] = useState(0);
  const [nowMs, setNowMs] = useState(Date.now());

  useEffect(() => {
    if (challengeId) {
      setSelectedChallengeById(parseInt(challengeId));
    }
  }, [challengeId, setSelectedChallengeById]);

  // Set default selected task if none is selected and tasks are available
  useEffect(() => {
    if (selectedChallenge?.tasks?.length > 0 && !selectedTask) {
      setSelectedTask(selectedChallenge.tasks[0]);
    }
  }, [selectedChallenge, selectedTask, setSelectedTask]);

  // Tick timer every second
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
          
          setSelectedSubmission(prev => {
            if (!prev) return null;
            const updated = data.items.find(s => s.id === prev.id);
            return updated ? { ...prev, ...updated } : prev;
          });
        } else {
          const arr = data || [];
          setSubmissions(arr);
          setSubmissionsTotal(arr.length);
          setSubmissionsPages(1);
          
          setSelectedSubmission(prev => {
            if (!prev) return null;
            const updated = arr.find(s => s.id === prev.id);
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

  // Reset page when selected task changes
  useEffect(() => {
    setSubmissionsPage(1);
  }, [selectedTask]);

  // Stream submissions via Server-Sent Events (SSE)
  useEffect(() => {
    if (!selectedTask) {
      setSubmissions([]);
      return;
    }

    setLoading(true);

    const tokenQuery = token ? `&token=${encodeURIComponent(token)}` : '';
    const sseUrl = `/api/tasks/${selectedTask.id}/submissions/live?page=${submissionsPage}&per_page=10${tokenQuery}`;
    const eventSource = new EventSource(sseUrl);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data) {
          if (data.items !== undefined) {
            setSubmissions(data.items || []);
            setSubmissionsTotal(data.total || 0);
            setSubmissionsPages(data.pages || 1);
            
            setSelectedSubmission(prev => {
              if (!prev) return null;
              const updated = data.items.find(s => s.id === prev.id);
              return updated ? { ...prev, ...updated } : prev;
            });
          } else {
            const arr = data || [];
            setSubmissions(arr);
            setSubmissionsTotal(arr.length);
            setSubmissionsPages(1);
            
            setSelectedSubmission(prev => {
              if (!prev) return null;
              const updated = arr.find(s => s.id === prev.id);
              return updated ? { ...prev, ...updated } : prev;
            });
          }
        }
        setLoading(false);
      } catch (err) {
        console.error("Failed to parse submissions SSE data:", err);
      }
    };

    eventSource.onerror = (err) => {
      console.error("Submissions SSE error, attempting HTTP fallback:", err);
      eventSource.close();

      const loadSubmissionsFallback = async () => {
        try {
          const res = await TaskService.getSubmissions(selectedTask.id, submissionsPage, 10);
          if (res.ok) {
            const data = res.data;
            if (data && data.items !== undefined) {
              setSubmissions(data.items || []);
              setSubmissionsTotal(data.total || 0);
              setSubmissionsPages(data.pages || 1);
            } else {
              const arr = data || [];
              setSubmissions(arr);
              setSubmissionsTotal(arr.length);
              setSubmissionsPages(1);
            }
          }
        } catch (fetchErr) {
          console.error("Fallback submissions fetch failed:", fetchErr);
        } finally {
          setLoading(false);
        }
      };

      loadSubmissionsFallback();
    };

    return () => {
      eventSource.close();
    };
  }, [selectedTask, submissionsPage, token]);


  const handleSelectFinal = async (submissionId) => {
    setSelectingFinal(true);
    try {
      const res = await api.fetch(`/api/submissions/${submissionId}/select-final`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });
      if (res.ok) {
        fetchSubmissions(true);
      } else {
        const data = await res.json();
        await confirm({
          title: t('submissions.selection_error'),
          message: data.code ? t(`api.${data.code}`, data.error || t('submissions.select_final_failed')) : (data.error || t('submissions.select_final_failed')),
          confirmText: t('common.ok'),
          cancelText: ""
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
      if (res.ok) {
        setSelectedSubmission(prev => prev && prev.id === sub.id ? { ...prev, ...res.data } : prev);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const stage = selectedChallenge?.stages?.find(s => s.id === selectedTask?.stage_id);
  
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
            if (tSelect > finalSelectDeadline) {
              finalSelectDeadline = tSelect;
            }
          } else if (sub.status === 'queued' || sub.status === 'running') {
            hasRunningPreDeadline = true;
          }
        }
      }
    }
  }

  const isSelectionDisabled = stage 
    ? (!hasRunningPreDeadline && finalSelectDeadline !== null && nowMs > finalSelectDeadline)
    : false;

  const isSubmissionAfterDeadline = stage && selectedSubmission 
    ? new Date(selectedSubmission.created_at).getTime() > new Date(stage.end_time).getTime()
    : false;

  const renderTimer = () => {
    if (!stage) return null;
    let timerText = '';
    let isExpired = false;

    if (hasRunningPreDeadline) {
      timerText = t('submissions.waiting_for_evaluation');
    } else if (finalSelectDeadline) {
      const diff = finalSelectDeadline - nowMs;
      if (diff <= 0) {
        timerText = t('submissions.selection_closed');
        isExpired = true;
      } else {
        const min = Math.floor(diff / 60000);
        const sec = Math.floor((diff % 60000) / 1000);
        timerText = t('submissions.time_remaining_select_final', { time: `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}` });
      }
    }

    return (
      <div style={{
        fontSize: '0.8rem',
        fontWeight: 600,
        color: isExpired ? 'var(--danger)' : 'var(--warning)',
        background: isExpired ? 'rgba(239, 68, 68, 0.1)' : 'rgba(245, 158, 11, 0.1)',
        border: `1px solid ${isExpired ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.2)'}`,
        borderRadius: 'var(--radius-md)',
        padding: '10px 14px',
        textAlign: 'center',
      }}>
        {timerText}
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {selectedChallenge ? (
        <>
          {/* Task selector if there are multiple tasks */}
          {selectedChallenge.tasks?.length > 1 && (
            <div className="surface" style={{ padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                {t('submissions.select_task')}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <TabScrollContainer>
                  {selectedChallenge.tasks.map(task => (
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
                </TabScrollContainer>
              </div>
            </div>
          )}

          {selectedTask ? (
            <div key={selectedTask.id} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {renderTimer()}
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr',
                gap: 24,
              }} className="lg:grid-cols-[320px_1fr] items-start animate-fadein">
                
                {/* Left Column: Submissions List */}
                <SubmissionList 
                  submissions={submissions}
                  selected={selectedSubmission}
                  onSelect={handleSelectSubmission}
                  loading={loading}
                  page={submissionsPage}
                  pages={submissionsPages}
                  total={submissionsTotal}
                  perPage={10}
                  onPageChange={setSubmissionsPage}
                />

                {/* Right Column: Submission Viewer */}
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
        </>
      ) : (
        <EmptyState message={t('submissions.no_competition_selected')} minHeight={200} />
      )}
    </div>
  );
}
