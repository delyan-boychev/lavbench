import React from 'react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Logo from '../ui/Logo';
import Badge from '../ui/Badge';
import Modal from '../ui/Modal';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '../ui/MarkdownComponents';

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
  const [isDocsModalOpen, setIsDocsModalOpen] = React.useState(false);
  const [activeDocTab, setActiveDocTab] = React.useState('student');
  const [docContent, setDocContent] = React.useState('');
  const [docLoading, setDocLoading] = React.useState(false);
  const [docError, setDocError] = React.useState(null);

  const docTabs = React.useMemo(() => {
    const tabs = [{ id: 'student', label: 'Student Guide' }];
    if (currentUser?.role === 'jury' || currentUser?.role === 'admin') {
      tabs.push({ id: 'jury', label: 'Jury Guide' });
    }
    if (currentUser?.role === 'admin') {
      tabs.push({ id: 'admin', label: 'Admin Guide' });
      tabs.push({ id: 'api-reference', label: 'API Reference' });
    }
    return tabs;
  }, [currentUser]);

  React.useEffect(() => {
    if (!token || !isDocsModalOpen) return;
    
    const fetchDoc = async () => {
      setDocLoading(true);
      setDocError(null);
      try {
        const res = await fetch(`/api/docs/${activeDocTab}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          setDocContent(data.content);
        } else {
          const errData = await res.json();
          setDocError(errData.error || 'Failed to fetch documentation.');
        }
      } catch (err) {
        setDocError('Failed to fetch documentation due to a network error.');
      } finally {
        setDocLoading(false);
      }
    };
    
    fetchDoc();
  }, [token, isDocsModalOpen, activeDocTab]);

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

        {/* Center: Cluster status & Docs */}
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button 
            onClick={() => setIsModalOpen(prev => !prev)}
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
            Cluster
          </button>

          {currentUser && (
            <button 
              onClick={() => setIsDocsModalOpen(true)}
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
                cursor: 'pointer',
                outline: 'none',
                transition: 'all 0.2s ease',
              }}
              className="hover:scale-[1.02] active:scale-[0.98] select-none"
              title="System Documentation & Guides"
            >
              <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
              Docs
            </button>
          )}
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

      <Modal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        title="Cluster Info & Active Node Specifications"
        size="md"
        footer={(
          <button 
            className="btn btn-secondary btn-sm px-4" 
            onClick={() => setIsModalOpen(false)}
          >
            Close
          </button>
        )}
      >
        <div className="flex flex-col gap-4 text-xs text-left">
          <p className="text-slate-400">
            Real-time specifications of available processing nodes connected to the competition queue.
          </p>

          {/* Cluster Status Summary Info Card */}
          <div className="bg-slate-950/60 border border-indigo-500/10 p-4 rounded-xl flex flex-col gap-2">
            <h4 className="font-bold text-slate-200 text-xs uppercase tracking-wider mb-1 text-indigo-400">Cluster Status Summary</h4>
            <div className="grid grid-cols-2 gap-3 text-slate-300">
              <div className="flex justify-between border-b border-white/5 pb-1.5">
                <span className="text-slate-400">System Status:</span>
                <span className="font-bold text-emerald-400">Active</span>
              </div>
              <div className="flex justify-between border-b border-white/5 pb-1.5">
                <span className="text-slate-400">Total Nodes:</span>
                <span className="font-bold text-slate-100">{clusters.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Global Concurrency:</span>
                <span className="font-bold text-slate-100">
                  {clusters.reduce((acc, c) => acc + (c.concurrency || 0), 0)} parallel tasks
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Resource Routing:</span>
                <span className="font-bold text-indigo-400">Automatic (Load Balanced)</span>
              </div>
            </div>
          </div>
          
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

      {/* System Documentation Modal */}
      <Modal
        isOpen={isDocsModalOpen}
        onClose={() => setIsDocsModalOpen(false)}
        title="Documentation & Guides"
        size="xl"
        footer={(
          <button 
            className="btn btn-secondary btn-sm px-4" 
            onClick={() => setIsDocsModalOpen(false)}
          >
            Close
          </button>
        )}
      >
        <div className="flex flex-col gap-4 text-left h-[70vh] md:h-[75vh]">
          {/* Tabs header - scrollable horizontally on small viewports */}
          {docTabs.length > 1 && (
            <div className="flex gap-2 border-b border-white/5 pb-2 overflow-x-auto scrollbar-none whitespace-nowrap">
              {docTabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveDocTab(tab.id)}
                  className={`px-3 py-1.5 rounded-lg font-semibold transition-all duration-200 cursor-pointer ${
                    activeDocTab === tab.id 
                      ? 'bg-indigo-600/10 text-indigo-400 border border-indigo-500/30' 
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          )}
          
          {/* Scrollable Doc Content Area */}
          <div className="flex-1 overflow-y-auto pr-3 scrollbar-thin">
            {docLoading ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-500 gap-2">
                <div className="animate-spin h-6 w-6 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
                <span>Loading documentation...</span>
              </div>
            ) : docError ? (
              <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl text-center">
                {docError}
              </div>
            ) : (
              <div className="prose prose-invert max-w-none text-slate-300">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {docContent}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </Modal>
    </header>
  );
}
