import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import ChallengeService from '../services/ChallengeService';
import LeaderboardTable from '../components/leaderboard/LeaderboardTable';
import EmptyState from '../components/ui/EmptyState';
import { useTranslation } from 'react-i18next';

export default function LeaderboardView() {
  const { challengeId } = useParams();
  const { selectedChallenge, setSelectedChallengeById } = useApp();
  const { t } = useTranslation();

  const [leaderboardData, setLeaderboardData] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [metricName, setMetricName] = useState('Score');
  const [isNormalized, setIsNormalized] = useState(false);

  const [useSse, setUseSse] = useState(true);

  useEffect(() => {
    if (challengeId) {
      setSelectedChallengeById(challengeId);
    }
  }, [challengeId, setSelectedChallengeById]);

  useEffect(() => {
    // Reset SSE usage if challenge changes
    setUseSse(true);
  }, [challengeId, selectedChallenge?.id]);

  const loadLeaderboard = async (showLoading = true) => {
    const activeId = challengeId || selectedChallenge?.id;
    if (!activeId) return;
    if (showLoading) setLoading(true);
    try {
      const res = await ChallengeService.getLeaderboard(activeId);
      if (res.ok) {
        setLeaderboardData(res.data.leaderboard || []);
        setTasks(res.data.tasks || []);
        setMetricName(res.data.metric_name || 'Score');
        setIsNormalized(res.data.is_normalized || false);
      }
    } catch (err) {
      console.error('Failed to load challenge leaderboard:', err);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    const activeId = challengeId || selectedChallenge?.id;
    if (!activeId) return;

    loadLeaderboard(true); // eslint-disable-line react-hooks/set-state-in-effect

    if (useSse && typeof EventSource !== 'undefined') {
      const sseUrl = `/api/challenges/${activeId}/leaderboard/live`;
      const eventSource = new EventSource(sseUrl);

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.info === 'connected') return;
          setLeaderboardData(data.leaderboard || []);
          setTasks(data.tasks || []);
          setMetricName(data.metric_name || 'Score');
          setIsNormalized(data.is_normalized || false);
        } catch (err) {
          console.error('Failed to parse live leaderboard update:', err);
        }
      };

      eventSource.onerror = () => {
        console.warn('Leaderboard SSE failed, falling back to polling.');
        eventSource.close();
        setUseSse(false);
      };

      return () => {
        eventSource.close();
      };
    } else {
      if (useSse) {
        setUseSse(false);
      }
      const interval = setInterval(() => {
        loadLeaderboard(false);
      }, 15000);

      return () => clearInterval(interval);
    }
  }, [challengeId, selectedChallenge?.id]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {selectedChallenge ? (
        <LeaderboardTable
          data={leaderboardData}
          tasks={tasks}
          challenge={selectedChallenge}
          loading={loading}
          metricName={metricName}
          isNormalized={isNormalized}
          onRefresh={() => loadLeaderboard(true)}
        />
      ) : (
        <EmptyState message={t('challenge.no_competition_selected_brief')} minHeight={200} />
      )}
    </div>
  );
}
