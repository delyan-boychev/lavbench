import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import ChallengeService from '../services/ChallengeService';
import LeaderboardTable from '../components/leaderboard/LeaderboardTable';
import EmptyState from '../components/ui/EmptyState';

export default function LeaderboardView() {
  const { challengeId } = useParams();
  const { 
    selectedChallenge, 
    setSelectedChallengeById 
  } = useApp();

  const [leaderboardData, setLeaderboardData] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (challengeId) {
      setSelectedChallengeById(parseInt(challengeId));
    }
  }, [challengeId, setSelectedChallengeById]);

  const loadLeaderboard = async (showLoading = true) => {
    if (!challengeId) return;
    if (showLoading) setLoading(true);
    try {
      const res = await ChallengeService.getLeaderboard(challengeId);
      if (res.ok) {
        setLeaderboardData(res.data.leaderboard || []);
        setTasks(res.data.tasks || []);
      }
    } catch (err) {
      console.error("Failed to load challenge leaderboard:", err);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    loadLeaderboard(true);

    const interval = setInterval(() => {
      loadLeaderboard(false);
    }, 15000);

    return () => clearInterval(interval);
  }, [challengeId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {selectedChallenge ? (
        <LeaderboardTable 
          data={leaderboardData} 
          tasks={tasks}
          challenge={selectedChallenge} 
          loading={loading}
          onRefresh={() => loadLeaderboard(true)}
        />
      ) : (
        <EmptyState message="No competition selected." minHeight={200} />
      )}
    </div>
  );
}
