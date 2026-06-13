import React from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';

function TabIcon({ name }) {
  const icons = {
    challenge: <path d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />,
    leaderboard: <path d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />,
    submissions: <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />,
    admin: <path d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />,
  };
  return (
    <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {icons[name]}
    </svg>
  );
}

function getNavClass({ isActive }) {
  return `nav-tab${isActive ? ' active' : ''}`;
}

export default function CompetitionBar() {
  const { currentUser } = useAuth();
  const { challenges, selectedChallenge, setSelectedChallengeById } = useApp();

  return (
    <div style={{
      background: 'rgba(9, 10, 15, 0.8)',
      borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
      position: 'sticky',
      top: 56,
      zIndex: 90,
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
    }}>
      <div style={{
        maxWidth: 1400,
        margin: '0 auto',
        padding: '0 24px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        minHeight: 48,
      }}>
        {/* Competition selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <span style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>
            Competition
          </span>
          <select
            className="surface-input"
            style={{ padding: '5px 10px', maxWidth: 280, minWidth: 160, cursor: 'pointer' }}
            value={selectedChallenge?.id || ''}
            onChange={e => setSelectedChallengeById(parseInt(e.target.value))}
          >
            {challenges.length === 0 && <option value="">No competitions</option>}
            {challenges.map(c => (
              <option key={c.id} value={c.id}>
                {c.title}{c.is_archived ? ' (Archived)' : ''}
              </option>
            ))}
          </select>
          {selectedChallenge?.is_archived && (
            <span className="pill pill-muted">Archived</span>
          )}
        </div>

        {/* Tab navigation */}
        <nav style={{ display: 'flex', gap: 4, overflowX: 'auto', padding: '4px 0' }}>
          <NavLink to={selectedChallenge ? `/challenges/${selectedChallenge.id}` : "/challenges"} end className={getNavClass} id="tab-challenge">
            <TabIcon name="challenge" />
            <span>Challenge</span>
          </NavLink>
          <NavLink to={selectedChallenge ? `/challenges/${selectedChallenge.id}/leaderboard` : "/leaderboard"} end className={getNavClass} id="tab-leaderboard">
            <TabIcon name="leaderboard" />
            <span>Leaderboard</span>
          </NavLink>
          <NavLink to={selectedChallenge ? `/challenges/${selectedChallenge.id}/submissions` : "/submissions"} end className={getNavClass} id="tab-submissions">
            <TabIcon name="submissions" />
            <span>Submissions</span>
          </NavLink>
          {(currentUser?.role === 'admin' || currentUser?.role === 'jury') && (
            <NavLink to="/admin" className={getNavClass} id="tab-admin">
              <TabIcon name="admin" />
              <span>Admin Panel</span>
            </NavLink>
          )}
        </nav>
      </div>
    </div>
  );
}
