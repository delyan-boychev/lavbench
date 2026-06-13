import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useAuth } from '../AuthContext';
import TaskService from '../services/TaskService';
import LeaderboardTable from '../components/leaderboard/LeaderboardTable';

export default function LeaderboardView() {
  const { challengeId } = useParams();
  const { token } = useAuth();
  const { 
    selectedChallenge, 
    setSelectedChallengeById, 
    selectedTask, 
    setSelectedTask 
  } = useApp();

  const [leaderboardData, setLeaderboardData] = useState([]);
  const [loading, setLoading] = useState(false);

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

  // Stream leaderboard data via Server-Sent Events (SSE)
  useEffect(() => {
    if (!selectedTask) {
      setLeaderboardData([]);
      return;
    }

    setLoading(true);

    const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : '';
    const sseUrl = `/api/tasks/${selectedTask.id}/leaderboard/live${tokenQuery}`;
    const eventSource = new EventSource(sseUrl);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data && data.leaderboard) {
          setLeaderboardData(data.leaderboard);
        }
        setLoading(false);
      } catch (err) {
        console.error("Failed to parse leaderboard SSE data:", err);
      }
    };

    eventSource.onerror = (err) => {
      console.error("Leaderboard SSE error, attempting HTTP fallback:", err);
      eventSource.close();

      const loadDataFallback = async () => {
        try {
          const res = await TaskService.getLeaderboard(selectedTask.id);
          if (res.ok) {
            setLeaderboardData(res.data.leaderboard || []);
          }
        } catch (fetchErr) {
          console.error("Fallback leaderboard fetch failed:", fetchErr);
        } finally {
          setLoading(false);
        }
      };

      loadDataFallback();
    };

    return () => {
      eventSource.close();
    };
  }, [selectedTask, token]);


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
                    onClick={() => setSelectedTask(t)}
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
            <LeaderboardTable 
              data={leaderboardData} 
              challenge={selectedChallenge} 
              loading={loading}
              onFinalize={() => {}} // Handler is inside LeaderboardTable
            />
          ) : (
            <div className="surface empty-state" style={{ minHeight: 200 }}>
              <p>Please select a task to view the leaderboard.</p>
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
