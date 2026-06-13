import React from 'react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Logo from '../ui/Logo';
import Badge from '../ui/Badge';
import Modal from '../ui/Modal';

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
  const [clusters, setClusters] = React.useState([]);
  const [isModalOpen, setIsModalOpen] = React.useState(false);

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
          setClusters(data.clusters || []);
        } else {
          setWorkerStatus('offline');
          setClusters([]);
        }
      } catch {
        setWorkerStatus('offline');
        setClusters([]);
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

        {/* Center: Cluster status */}
        <button 
          onClick={() => setIsModalOpen(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 12px',
            background: workerStatus === 'online' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
            border: `1px solid ${workerStatus === 'online' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.72rem',
            fontWeight: 700,
            color: workerStatus === 'online' ? '#10b981' : '#ef4444',
            cursor: 'pointer',
            outline: 'none',
            transition: 'all 0.2s ease',
          }}
          className="hover:scale-[1.02] active:scale-[0.98] select-none"
          title="View Available Clusters"
        >
          <span style={{ 
            position: 'relative',
            display: 'flex',
            width: 8, 
            height: 8, 
          }}>
            {workerStatus === 'online' && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            )}
            <span className={`relative inline-flex rounded-full h-2 w-2 ${workerStatus === 'online' ? 'bg-emerald-500' : 'bg-rose-500'}`}></span>
          </span>
          {workerStatus === 'online' ? 'Cluster Online' : 'Cluster Offline'}
        </button>

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

      {/* Clusters List Modal */}
      <Modal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        title="Active Cluster Node Specifications"
        size="md"
      >
        <div className="flex flex-col gap-4 text-xs text-left">
          <p className="text-slate-400">
            Real-time specifications of available processing nodes connected to the competition queue.
          </p>
          
          {clusters.length === 0 ? (
            <div className="text-center py-8 text-slate-500 italic bg-slate-950/20 border border-white/5 rounded-xl">
              No active processing nodes currently connected.
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {clusters.map((cluster, idx) => (
                <div key={cluster.name || idx} className="bg-slate-950/40 border border-white/5 p-4 rounded-xl flex flex-col gap-3">
                  <div className="flex justify-between items-center">
                    <span className="font-mono text-indigo-400 font-bold text-sm">{cluster.name}</span>
                    <span className={`px-2 py-0.5 text-[9px] font-bold rounded-full border ${
                      cluster.type === 'GPU' ? 'bg-indigo-500/10 border-indigo-500/20 text-indigo-400' : 'bg-slate-800 border-slate-700 text-slate-300'
                    }`}>
                      {cluster.type} Node
                    </span>
                  </div>
                  
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2.5 text-slate-300 font-medium">
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">Concurrency:</span>
                      <span className="font-bold text-slate-200">{cluster.concurrency} tasks</span>
                    </div>
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">RAM Limit:</span>
                      <span className="font-bold text-slate-200">{cluster.ram_gb} GB</span>
                    </div>
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">GPU Model:</span>
                      <span className="font-bold text-slate-200 truncate max-w-[140px] text-right" title={cluster.gpu_type}>{cluster.gpu_type}</span>
                    </div>
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">VRAM Limit:</span>
                      <span className="font-bold text-slate-200">{cluster.vram_gb !== 'N/A' && cluster.vram_gb !== null ? `${cluster.vram_gb} GB` : 'N/A'}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </header>
  );
}
