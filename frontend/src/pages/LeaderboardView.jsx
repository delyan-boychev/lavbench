import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import useSSE from '../hooks/useSSE';
import ChallengeService from '../services/ChallengeService';
import LeaderboardTable from '../components/leaderboard/LeaderboardTable';
import EmptyState from '../components/ui/EmptyState';
import { useTranslation } from 'react-i18next';

export default function LeaderboardView() {
  const { challengeId } = useParams();
  const { selectedChallenge, setSelectedChallengeById, fetchChallenges } = useApp();
  const { t } = useTranslation();

  const [leaderboardData, setLeaderboardData] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [metricName, setMetricName] = useState('Score');
  const [isNormalized, setIsNormalized] = useState(false);

  const [useSse, setUseSse] = useState(true);

  const activeId = challengeId || selectedChallenge?.id;
  const hasSse = typeof EventSource !== 'undefined';

  useSSE(useSse && hasSse && activeId ? `/api/challenges/${activeId}/leaderboard/live` : '', {
    onMessage: (data) => {
      if (data.info === 'connected') return;
      setLeaderboardData(data.leaderboard || []);
      setTasks(data.tasks || []);
      setMetricName(data.metric_name || 'Score');
      setIsNormalized(data.is_normalized || false);
    },
    onError: () => {
      setUseSse(false);
    },
  });

  useEffect(() => {
    if (challengeId) {
      setSelectedChallengeById(challengeId);
    }
  }, [challengeId, setSelectedChallengeById]);

  useEffect(() => {
    setUseSse(true);
  }, [challengeId, selectedChallenge?.id]);

  const loadLeaderboard = useCallback(
    async (showLoading = true) => {
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
    },
    [challengeId, selectedChallenge?.id],
  );

  useEffect(() => {
    const activeId = challengeId || selectedChallenge?.id;
    if (activeId) {
      loadLeaderboard(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challengeId, selectedChallenge?.id]);

  useEffect(() => {
    const activeId = challengeId || selectedChallenge?.id;
    if (!activeId) return;

    if (!hasSse || !useSse) {
      const interval = setInterval(() => {
        loadLeaderboard(false);
      }, 15000);
      return () => clearInterval(interval);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challengeId, selectedChallenge?.id, useSse, hasSse]);

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
          onRefresh={async () => {
            await fetchChallenges();
            loadLeaderboard(true);
          }}
        />
      ) : (
        <EmptyState message={t('challenge.no_competition_selected_brief')} minHeight={200} />
      )}
    </div>
  );
}
