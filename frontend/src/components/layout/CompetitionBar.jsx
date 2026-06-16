import React from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import CustomSelect from '../ui/CustomSelect';
import { useTranslation } from 'react-i18next';
import { Layout, Trophy, Pencil, Shield } from 'lucide-react';

function TabIcon({ name }) {
  const iconStyle = { flexShrink: 0 };
  switch (name) {
    case 'challenge': return <Layout size={18} style={iconStyle} />;
    case 'leaderboard': return <Trophy size={18} style={iconStyle} />;
    case 'submissions': return <Pencil size={18} style={iconStyle} />;
    case 'admin': return <Shield size={18} style={iconStyle} />;
    default: return null;
  }
}

function getNavClass({ isActive }) {
  return `nav-tab${isActive ? ' active' : ''}`;
}

export default function CompetitionBar() {
  const { currentUser } = useAuth();
  const { challenges, selectedChallenge, setSelectedChallengeById } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const isTabActive = (tab) => {
    const path = location.pathname;
    if (tab === 'challenge') {
      return path === '/challenges' || (path.startsWith('/challenges/') && !path.endsWith('/leaderboard') && !path.endsWith('/submissions'));
    }
    if (tab === 'leaderboard') {
      return path === '/leaderboard' || (path.startsWith('/challenges/') && path.endsWith('/leaderboard'));
    }
    if (tab === 'submissions') {
      return path === '/submissions' || (path.startsWith('/challenges/') && path.endsWith('/submissions'));
    }
    if (tab === 'admin') {
      return path.startsWith('/admin');
    }
    return false;
  };

  const getNavTabClass = (tab) => {
    return `nav-tab${isTabActive(tab) ? ' active' : ''}`;
  };

  const handleChallengeChange = (val) => {
    if (!val) return;
    const newId = parseInt(val);
    setSelectedChallengeById(newId);

    const path = location.pathname;
    if (path.startsWith('/challenges')) {
      const parts = path.split('/');
      if (parts.length > 3) {
        navigate(`/challenges/${newId}/${parts[3]}`);
      } else {
        navigate(`/challenges/${newId}`);
      }
    } else if (path === '/leaderboard') {
      navigate(`/challenges/${newId}/leaderboard`);
    } else if (path === '/submissions') {
      navigate(`/challenges/${newId}/submissions`);
    }
  };

  return (
    <div style={{
      background: 'var(--bg-bar)',
      borderBottom: '1px solid var(--border)',
      position: 'sticky',
      top: 56,
      zIndex: 90,
      backdropFilter: 'blur(10px)',
      WebkitBackdropFilter: 'blur(10px)',
    }}>
      <div style={{
        maxWidth: 1400,
        margin: '0 auto',
        padding: '8px 12px',
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
            {t('nav.competition_label')}
          </span>
          {currentUser?.role === 'competitor' ? (
            <div 
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 12px',
                background: 'rgba(99, 102, 241, 0.08)',
                border: '1px solid rgba(99, 102, 241, 0.2)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.72rem',
                fontWeight: 700,
                color: 'rgb(129, 140, 248)',
                userSelect: 'none',
              }}
              title={t('nav.assigned_competition_tooltip')}
              data-testid="student-competition-label"
            >
              <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v13m0-13V6a2 2 0 112 2h-2zm0 0V5a2 2 0 10-2 2h2zm-7 2h14v2a7 7 0 01-14 0V9z" />
              </svg>
              <span>{selectedChallenge ? selectedChallenge.title : t('nav.no_competition_assigned')}</span>
            </div>
          ) : (
            <CustomSelect
              options={challenges.map(c => ({
                value: c.id,
                label: `${c.title}${c.is_archived ? t('nav.archived_suffix') : ''}`
              }))}
              value={selectedChallenge?.id || ''}
              onChange={handleChallengeChange}
              placeholder={t('nav.no_competitions_placeholder')}
              size="sm"
            />
          )}
          {selectedChallenge?.is_archived && (
            <span className="pill pill-muted">{t('nav.archived_pill')}</span>
          )}
        </div>

        {/* Tab navigation */}
        <nav style={{ display: 'flex', gap: 4, overflowX: 'auto', padding: '4px 0' }}>
          <NavLink to={selectedChallenge ? `/challenges/${selectedChallenge.id}` : "/challenges"} end className={getNavTabClass('challenge')} id="tab-challenge">
            <TabIcon name="challenge" />
            <span>{t('nav.challenge_tab')}</span>
          </NavLink>
          <NavLink to={selectedChallenge ? `/challenges/${selectedChallenge.id}/leaderboard` : "/leaderboard"} end className={getNavTabClass('leaderboard')} id="tab-leaderboard">
            <TabIcon name="leaderboard" />
            <span>{t('nav.leaderboard_tab')}</span>
          </NavLink>
          <NavLink to={selectedChallenge ? `/challenges/${selectedChallenge.id}/submissions` : "/submissions"} end className={getNavTabClass('submissions')} id="tab-submissions">
            <TabIcon name="submissions" />
            <span>{t('nav.submissions_tab')}</span>
          </NavLink>
          {(currentUser?.role === 'admin' || currentUser?.role === 'jury') && (
            <NavLink to="/admin" className={getNavTabClass('admin')} id="tab-admin">
              <TabIcon name="admin" />
              <span>{t('nav.admin_panel_tab')}</span>
            </NavLink>
          )}
        </nav>
      </div>
    </div>
  );
}
