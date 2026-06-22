import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

const NAMES = ['Alpha-Titan', 'Quantum-Falcon', 'Stellar-Voyager', 'Cyber-Phoenix', 'Neon-Warrior',
  'Pixel-Gladiator', 'Shadow-Ninja', 'Thunder-Dragon', 'Ice-Wizard', 'Blaze-Knight'];

function generateScores() {
  return NAMES.map((name, i) => ({
    id: i,
    name: `${name}-${100 + i}`,
    score: Math.round((0.5 + Math.random() * 0.5) * 10000) / 10000,
  })).sort((a, b) => b.score - a.score);
}

export default function LeaderboardDemo() {
  useTranslation();
  const [entries, setEntries] = useState(generateScores);
  const [prevRanks, setPrevRanks] = useState({});

  const shuffle = () => {
    const prev = {};
    entries.forEach((e, i) => { prev[e.id] = i; });
    setPrevRanks(prev);
    setEntries(generateScores());
  };

  // Animate on mount
  useEffect(() => {
    const timer = setInterval(shuffle, 3000); // eslint-disable-line react-hooks/set-state-in-effect
    return () => clearInterval(timer);
  }, []);

  const getDelta = (id, currentIndex) => {
    const prev = prevRanks[id];
    if (prev === undefined) return 0;
    return prev - currentIndex; // positive = went up, negative = went down
  };

  return (
    <div className="min-h-screen bg-slate-950 p-8 flex flex-col items-center gap-6 animate-fadein">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-white mb-2">Leaderboard Animation Demo</h1>
        <p className="text-sm text-slate-400">Scores shuffle every 3 seconds — watch the ranks change</p>
      </div>

      <button
        onClick={shuffle}
        className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-xl transition-all cursor-pointer text-sm"
      >
        Shuffle Now
      </button>

      <div className="w-full max-w-lg bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-800 flex items-center gap-3 text-[10px] font-bold text-slate-500 uppercase tracking-wider">
          <span className="w-8 text-center">Rank</span>
          <span className="flex-1">Participant</span>
          <span className="w-20 text-right">Score</span>
          <span className="w-16 text-center">Change</span>
        </div>

        {entries.map((entry, idx) => {
          const delta = getDelta(entry.id, idx);
          const medal = idx < 3 ? ['text-amber-300', 'text-slate-300', 'text-amber-600'][idx] : '';

          return (
            <div
              key={entry.id}
              className={`px-5 py-3.5 border-b border-slate-800/50 flex items-center gap-3 text-sm transition-all duration-700 ease-out ${
                delta !== 0 ? 'animate-fadein' : ''
              }`}
            >
              {/* Rank */}
              <div className="w-8 text-center">
                <span className={`text-sm font-extrabold font-mono ${medal || 'text-slate-400'}`}>
                  {idx + 1}
                </span>
              </div>

              {/* Name */}
              <span className="flex-1 text-slate-200 font-medium truncate">{entry.name}</span>

              {/* Score */}
              <span className="w-20 text-right font-mono text-indigo-400 font-bold">
                {entry.score.toFixed(4)}
              </span>

              {/* Delta */}
              <div className="w-16 text-center">
                {delta > 0 && (
                  <span className="inline-flex items-center gap-0.5 text-emerald-400 font-bold text-xs animate-[slideUp_0.5s_ease-out]">
                    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"><path d="M12 4l-8 8h5v8h6v-8h5z"/></svg>
                    {delta}
                  </span>
                )}
                {delta < 0 && (
                  <span className="inline-flex items-center gap-0.5 text-rose-400 font-bold text-xs animate-[slideDown_0.5s_ease-out]">
                    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"><path d="M12 20l8-8h-5V4H9v8H4z"/></svg>
                    {Math.abs(delta)}
                  </span>
                )}
                {delta === 0 && (
                  <span className="text-slate-600 text-xs">—</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <style>{`
        @keyframes slideUp {
          from { transform: translateY(10px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
        @keyframes slideDown {
          from { transform: translateY(-10px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
      `}</style>
    </div>
  );
}
