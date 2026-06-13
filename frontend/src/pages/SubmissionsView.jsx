import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useAuth } from '../AuthContext';
import TaskService from '../services/TaskService';
import SubmissionList from '../components/submissions/SubmissionList';
import SubmissionViewer from '../components/submissions/SubmissionViewer';

export default function SubmissionsView() {
  const { challengeId } = useParams();
  const { currentUser, token } = useAuth();
  const { 
    selectedChallenge, 
    setSelectedChallengeById, 
    selectedTask, 
    setSelectedTask 
  } = useApp();

  const [submissions, setSubmissions] = useState([]);
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectingFinal, setSelectingFinal] = useState(false);

  const [submissionsPage, setSubmissionsPage] = useState(1);
  const [submissionsPages, setSubmissionsPages] = useState(1);
  const [submissionsTotal, setSubmissionsTotal] = useState(0);

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
            return updated || prev;
          });
        } else {
          const arr = data || [];
          setSubmissions(arr);
          setSubmissionsTotal(arr.length);
          setSubmissionsPages(1);
          
          setSelectedSubmission(prev => {
            if (!prev) return null;
            const updated = arr.find(s => s.id === prev.id);
            return updated || prev;
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
              return updated || prev;
            });
          } else {
            const arr = data || [];
            setSubmissions(arr);
            setSubmissionsTotal(arr.length);
            setSubmissionsPages(1);
            
            setSelectedSubmission(prev => {
              if (!prev) return null;
              const updated = arr.find(s => s.id === prev.id);
              return updated || prev;
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
      const res = await fetch(`/api/submissions/${submissionId}/select-final`, {
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
        alert(data.error || "Failed to set final submission.");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setSelectingFinal(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {selectedChallenge ? (
        <>
          {/* Task selector if there are multiple tasks */}
          {selectedChallenge.tasks?.length > 1 && (
            <div className="surface" style={{ padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Select Task:
              </span>
              <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
                {selectedChallenge.tasks.map(t => (
                  <button
                    key={t.id}
                    onClick={() => {
                      setSelectedTask(t);
                      setSelectedSubmission(null);
                    }}
                    className={`nav-tab ${selectedTask?.id === t.id ? 'active' : ''}`}
                    style={{ padding: '4px 12px', fontSize: '0.75rem' }}
                  >
                    {t.title}
                  </button>
                ))}
              </div>
            </div>
          )}

          {selectedTask ? (
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr',
              gap: 24,
            }} className="lg:grid-cols-[320px_1fr] items-start">
              
              {/* Left Column: Submissions List */}
              <SubmissionList 
                submissions={submissions}
                selected={selectedSubmission}
                onSelect={setSelectedSubmission}
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
              />

            </div>
          ) : (
            <div className="surface empty-state" style={{ minHeight: 200 }}>
              <p>Please select a task to view submissions.</p>
            </div>
          )}
        </>
      ) : (
        <div className="surface empty-state" style={{ minHeight: 200 }}>
          <p>No competition selected.</p>
        </div>
      )}
    </div>
  );
}
