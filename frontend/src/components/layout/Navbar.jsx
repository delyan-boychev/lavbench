import React from 'react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Logo from '../ui/Logo';
import Badge from '../ui/Badge';

function SunIcon() {
  return (
    <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="5" />
      <path strokeLinecap="round" d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
    </svg>
  );
}

export default function Navbar() {
  const { currentUser, logout, token } = useAuth();
  const { theme, toggleTheme, showToast } = useApp();
  const [workerStatus, setWorkerStatus] = React.useState('online');

  const handleLogout = () => {
    logout();
    showToast('Signed out successfully.');
  };

  React.useEffect(() => {
    if (!token) return;
    
    const checkStatus = async () => {
      try {
        const res = await fetch('/api/worker-status', {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          setWorkerStatus(data.status);
        } else {
          setWorkerStatus('offline');
        }
      } catch {
        setWorkerStatus('offline');
      }
    };

    checkStatus();
    const interval = setInterval(checkStatus, 10000);
    return () => clearInterval(interval);
  }, [token]);

  const displayName = currentUser?.name
    ? `${currentUser.name} ${currentUser.surname || ''}`.trim()
    : currentUser?.username;

  return (
    <header style={{
      background: 'rgba(9, 10, 15, 0.8)',
      borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
      position: 'sticky',
      top: 0,
      zIndex: 100,
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
    }}>
      <div style={{
        maxWidth: 1400,
        margin: '0 auto',
        padding: '0 24px',
        height: 56,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
      }}>
        {/* Left: Logo */}
        <Logo />

        {/* Center: GPU status (hidden on small screens) */}
        <div className="hidden sm:flex" style={{
          alignItems: 'center', gap: 6,
          padding: '4px 12px',
          background: workerStatus === 'online' ? 'var(--success-soft)' : 'var(--danger-soft)',
          border: `1px solid ${workerStatus === 'online' ? 'var(--success-border)' : 'var(--danger-border)'}`,
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.72rem', fontWeight: 600,
          color: workerStatus === 'online' ? 'var(--success)' : 'var(--danger)',
        }}>
          <span style={{ 
            width: 6, 
            height: 6, 
            borderRadius: '50%', 
            background: workerStatus === 'online' ? 'var(--success)' : 'var(--danger)' 
          }} />
          {workerStatus === 'online' ? 'GPU Cluster Online' : 'GPU Cluster Offline'}
        </div>

        {/* Right: user + controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* User info */}
          {currentUser && (
            <div className="hidden sm:flex" style={{ flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
              <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                {displayName}
              </span>
              <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
                <Badge status={currentUser.role} />
                <span style={{
                  fontSize: '0.68rem', color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}>
                  {currentUser.alias_id}
                </span>
              </div>
            </div>
          )}

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-secondary)',
              width: 32, height: 32,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--border-hover)'; }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
          >
            {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
          </button>

          {/* Logout */}
          <button
            onClick={handleLogout}
            className="btn btn-secondary btn-sm"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
