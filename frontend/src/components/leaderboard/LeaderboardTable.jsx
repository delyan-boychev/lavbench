import React from 'react';
import { useAuth } from '../../AuthContext';
import ChallengeService from '../../services/ChallengeService';
import { useApp } from '../../context/AppContext';
import Button from '../ui/Button';

const MEDALS = ['🥇', '🥈', '🥉'];

function Row({ entry, rank, isCurrentUser, isFinalized }) {
  const { currentUser } = useAuth();
  const medal = rank <= 3 ? MEDALS[rank - 1] : null;
  const showIdentity = isFinalized || isCurrentUser || currentUser?.role === 'admin';

  return (
    <tr className={`border-b border-slate-800/60 transition-colors duration-150 ${isCurrentUser ? 'bg-indigo-500/5' : ''}`}>
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          {/* Rank circle on the Left */}
          <div className="flex items-center justify-center w-7 h-7 rounded-full bg-slate-800/40 border border-slate-700/50">
            <span className="text-xs font-mono font-bold text-slate-400">
              {rank}
            </span>
          </div>

          {/* Participant Details */}
          <div>
            {showIdentity ? (
              <div>
                <div className="flex items-center gap-2 text-sm font-bold text-slate-100">
                  <span>
                    {entry.user 
                      ? (entry.user.name ? `${entry.user.name} ${entry.user.surname}` : entry.user.username) 
                      : '—'}
                  </span>
                  {medal && <span className="text-sm leading-none" title={`Rank ${rank}`}>{medal}</span>}
                  {isCurrentUser && <span className="text-[10px] font-extrabold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">You</span>}
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-slate-200">
                  {entry.user?.alias_id || '—'}
                </span>
                {medal && <span className="text-sm leading-none" title={`Rank ${rank}`}>{medal}</span>}
              </div>
            )}
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-right font-mono font-bold text-indigo-400 text-sm">
        {entry.public_score != null ? Number(entry.public_score).toFixed(4) : '—'}
      </td>
      {isFinalized && (
        <td className="px-4 py-3 text-right font-mono font-bold text-emerald-400 text-sm">
          {entry.private_score != null ? Number(entry.private_score).toFixed(4) : '—'}
        </td>
      )}
    </tr>
  );
}

export default function LeaderboardTable({ data, challenge, loading, onFinalize }) {
  const { currentUser } = useAuth();
  const { showToast, fetchChallenges } = useApp();
  const isFinalized = challenge?.scores_finalized;
  const metric = challenge?.metric_name || 'Score';
  const isAdmin = currentUser?.role === 'admin' || currentUser?.role === 'jury';

  const handleFinalize = async () => {
    if (!confirm(`Finalize scores for "${challenge.title}"? This will reveal competitor identities and private scores.`)) return;
    const res = await ChallengeService.finalize(challenge.id);
    if (res.ok) {
      showToast('Scores finalized — identities revealed.');
      fetchChallenges();
    } else {
      showToast(res.data?.error || 'Finalization failed.', 'error');
    }
  };

  if (loading) {
    return (
      <div className="surface empty-state min-h-[150px]">
        <div className="animate-spin w-6 h-6 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
        <p>Loading leaderboard...</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-100">Leaderboard</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Metric: <span className="text-indigo-400 font-semibold">{metric}</span>
            {' · '}{data.length} participant{data.length !== 1 ? 's' : ''}
            {isFinalized && <span className="pill pill-success ml-2">Finalized</span>}
          </p>
        </div>
        {isAdmin && !isFinalized && challenge && (
          <Button variant="secondary" size="sm" onClick={handleFinalize}>
            Finalize & Reveal Identities
          </Button>
        )}
      </div>

      {/* Table */}
      <div className="surface overflow-hidden">
        {data.length === 0 ? (
          <div className="empty-state py-12 px-6">
            <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" className="text-slate-500">
              <path strokeLinecap="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <p>No scored submissions yet. Be the first!</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3">Participant</th>
                  <th className="px-4 py-3 text-right">Public Score</th>
                  {isFinalized && <th className="px-4 py-3 text-right">Private Score</th>}
                </tr>
              </thead>
              <tbody>
                {data.map(entry => (
                  <Row
                    key={entry.id}
                    entry={entry}
                    rank={entry.rank}
                    isCurrentUser={entry.user?.id === currentUser?.id}
                    isFinalized={isFinalized}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

