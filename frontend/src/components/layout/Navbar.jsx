import React from 'react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Logo from '../ui/Logo';
import Badge from '../ui/Badge';
import Modal from '../ui/Modal';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '../ui/MarkdownComponents';
import { useTranslation } from 'react-i18next';

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
  const { theme, toggleTheme, showToast, selectedChallenge } = useApp();
  const { t, i18n } = useTranslation();
  const [workerStatus, setWorkerStatus] = React.useState('online');
  const [clusters, setClusters] = React.useState([]);
  const [isModalOpen, setIsModalOpen] = React.useState(false);
  const [isDocsModalOpen, setIsDocsModalOpen] = React.useState(false);
  const [activeDocTab, setActiveDocTab] = React.useState('student');
  const [docContent, setDocContent] = React.useState('');
  const [docLoading, setDocLoading] = React.useState(false);
  const [docError, setDocError] = React.useState(null);
  const [nowMs, setNowMs] = React.useState(Date.now());

  React.useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const activeStage = React.useMemo(() => {
    if (!selectedChallenge?.stages) return null;
    const now = nowMs;
    const graceMs = (selectedChallenge.deadline_grace_period_seconds || 60) * 1000;
    return selectedChallenge.stages.find(st => {
      const start = new Date(st.start_time).getTime();
      const end = new Date(st.end_time).getTime();
      return now >= start && now <= (end + graceMs) && !st.is_finalized;
    });
  }, [selectedChallenge, nowMs]);

  const timeRemainingMs = React.useMemo(() => {
    const now = nowMs;
    if (activeStage) {
      return new Date(activeStage.end_time).getTime() - now;
    }
    if (selectedChallenge?.end_time) {
      const start = new Date(selectedChallenge.start_time).getTime();
      const end = new Date(selectedChallenge.end_time).getTime();
      const graceMs = (selectedChallenge.deadline_grace_period_seconds || 60) * 1000;
      if (now >= start && now <= (end + graceMs) && !selectedChallenge.scores_finalized) {
        return end - now;
      }
    }
    return null;
  }, [activeStage, selectedChallenge, nowMs]);

  const renderNavbarTimer = () => {
    if (timeRemainingMs === null) return null;
    
    const graceMs = (selectedChallenge?.deadline_grace_period_seconds || 60) * 1000;
    const isGracePeriod = timeRemainingMs < 0;
    
    let color = '#10b981'; // Green
    let isFlashing = false;
    
    if (isGracePeriod) {
      color = '#f97316'; // Amber/Orange
      isFlashing = true;
    } else {
      const minutesLeft = timeRemainingMs / 60000;
      if (minutesLeft <= 5) {
        color = '#ef4444'; // Red
        isFlashing = true;
      } else if (minutesLeft <= 15) {
        color = '#ef4444'; // Red
      } else if (minutesLeft <= 30) {
        color = '#f59e0b'; // Yellow
      }
    }
    
    let timeStr = "";
    if (isGracePeriod) {
      const remainingGraceSecs = Math.ceil((graceMs + timeRemainingMs) / 1000);
      timeStr = `${remainingGraceSecs}s`;
    } else {
      const totalSecs = Math.ceil(timeRemainingMs / 1000);
      const hours = Math.floor(totalSecs / 3600);
      const minutes = Math.floor((totalSecs % 3600) / 60);
      const seconds = totalSecs % 60;
      timeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
    
    const labelStr = isGracePeriod 
      ? t('nav.grace_period')
      : (activeStage ? t('nav.stage_time_left', { stage: activeStage.stage_number }) : t('nav.time_left'));
      
    const titleStr = isGracePeriod
      ? t('nav.grace_period_title')
      : (activeStage ? t('nav.stage_time_left_title', { stage: activeStage.stage_number }) : t('nav.time_left_title'));
      
    return (
      <div 
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 12px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.78rem',
          fontWeight: 700,
          color: color,
          userSelect: 'none',
          transition: 'all 0.2s ease',
        }}
        className={isFlashing ? 'animate-flash-red' : ''}
        title={titleStr}
      >
        <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{labelStr}: {timeStr}</span>
      </div>
    );
  };

  const docTabs = React.useMemo(() => {
    const tabs = [{ id: 'student', label: t('nav.doc_student_guide') }];
    if (currentUser?.role === 'jury' || currentUser?.role === 'admin') {
      tabs.push({ id: 'jury', label: t('nav.doc_jury_guide') });
    }
    if (currentUser?.role === 'admin') {
      tabs.push({ id: 'admin', label: t('nav.doc_admin_guide') });
      tabs.push({ id: 'api-reference', label: t('nav.doc_api_reference') });
    }
    return tabs;
  }, [currentUser, t]);

  React.useEffect(() => {
    if (!token || !isDocsModalOpen) return;
    
    const fetchDoc = async () => {
      setDocLoading(true);
      setDocError(null);
      try {
        const res = await fetch(`/api/docs/${activeDocTab}?lang=${i18n.language || 'en'}`, {
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Accept-Language': i18n.language || 'en'
          }
        });
        if (res.ok) {
          const data = await res.json();
          setDocContent(data.content);
        } else {
          const errData = await res.json();
          setDocError(errData.code ? t(`api.${errData.code}`, errData.error || t('nav.failed_fetch_docs')) : (errData.error || t('nav.failed_fetch_docs')));
        }
      } catch (err) {
        setDocError(t('nav.failed_fetch_docs_network'));
      } finally {
        setDocLoading(false);
      }
    };
    
    fetchDoc();
  }, [token, isDocsModalOpen, activeDocTab]);

  const handleLogout = () => {
    logout();
    showToast(t('nav.signed_out_success'));
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
      background: 'var(--bg-nav)',
      borderBottom: '1px solid var(--border)',
      position: 'sticky',
      top: 0,
      zIndex: 100,
      backdropFilter: 'blur(10px)',
      WebkitBackdropFilter: 'blur(10px)',
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
          {renderNavbarTimer()}
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
            title={t('nav.cluster_info_title')}
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
            {t('nav.cluster')}
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
                color: 'var(--accent-border)',
                cursor: 'pointer',
                outline: 'none',
                transition: 'all 0.2s ease',
              }}
              className="hover:scale-[1.02] active:scale-[0.98] select-none"
              title={t('nav.docs_title')}
            >
              <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
              {t('nav.docs')}
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

          {/* Language Selector Selector */}
          <button
            onClick={() => i18n.changeLanguage(i18n.language.startsWith('bg') ? 'en' : 'bg')}
            title={i18n.language.startsWith('bg') ? 'Switch to English' : 'Премини на български'}
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-secondary)',
              fontSize: '0.72rem',
              fontWeight: 700,
              width: 32, height: 32,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              userSelect: 'none'
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--border-hover)'; }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
          >
            {i18n.language.startsWith('bg') ? 'EN' : 'BG'}
          </button>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? t('nav.switch_light') : t('nav.switch_dark')}
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
            {t('nav.sign_out')}
          </button>
        </div>
      </div>

      <Modal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        title={t('nav.cluster_info_title')}
        size="md"
        footer={(
          <button 
            className="btn btn-secondary btn-sm px-4" 
            onClick={() => setIsModalOpen(false)}
          >
            {t('nav.close')}
          </button>
        )}
      >
        <div className="flex flex-col gap-4 text-xs text-left">
          <p className="text-slate-400">
            {t('nav.cluster_info_desc')}
          </p>

          {/* Cluster Status Summary Info Card */}
          <div className="bg-slate-950/60 border border-indigo-500/10 p-4 rounded-xl flex flex-col gap-2">
            <h4 className="font-bold text-slate-200 text-xs uppercase tracking-wider mb-1 text-indigo-400">{t('nav.cluster_status_summary')}</h4>
            <div className="grid grid-cols-2 gap-3 text-slate-300">
              <div className="flex justify-between border-b border-white/5 pb-1.5">
                <span className="text-slate-400">{t('nav.system_status')}</span>
                <span className="font-bold text-emerald-400">{t('nav.active')}</span>
              </div>
              <div className="flex justify-between border-b border-white/5 pb-1.5">
                <span className="text-slate-400">{t('nav.total_nodes')}</span>
                <span className="font-bold text-slate-100">{clusters.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">{t('nav.global_concurrency')}</span>
                <span className="font-bold text-slate-100">
                  {t('nav.global_parallel_tasks', { count: clusters.reduce((acc, c) => acc + (c.concurrency || 0), 0) })}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">{t('nav.resource_routing')}</span>
                <span className="font-bold text-indigo-400">{t('nav.auto_load_balanced')}</span>
              </div>
            </div>
          </div>
          
          {clusters.length === 0 ? (
            <div className="text-center py-8 text-slate-500 italic bg-slate-950/20 border border-white/5 rounded-xl">
              {t('nav.no_nodes_connected')}
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
                      {t('nav.node_type', { type: cluster.type })}
                    </span>
                  </div>
                  
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2.5 text-slate-300 font-medium">
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">{t('nav.concurrency')}</span>
                      <span className="font-bold text-slate-200">{t('nav.parallel_tasks', { count: cluster.concurrency })}</span>
                    </div>
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">{t('nav.ram_limit')}</span>
                      <span className="font-bold text-slate-200">{cluster.ram_gb} GB</span>
                    </div>
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">{t('nav.gpu_model')}</span>
                      <span className="font-bold text-slate-200 truncate max-w-[140px] text-right" title={cluster.gpu_type}>{cluster.gpu_type}</span>
                    </div>
                    <div className="flex justify-between border-b border-white/5 pb-1">
                      <span className="text-slate-500 font-semibold">{t('nav.vram_limit')}</span>
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
        title={t('nav.docs_title')}
        size="2xl"
        bodyScrollable={false}
        footer={(
          <button 
            className="btn btn-secondary btn-sm px-4" 
            onClick={() => setIsDocsModalOpen(false)}
          >
            {t('nav.close')}
          </button>
        )}
      >
        <div className="flex flex-col gap-4 text-left flex-1 min-h-0">
          {/* Tabs header - scrollable horizontally on small viewports */}
          {docTabs.length > 1 && (
            <div className="flex gap-2 border-b border-white/5 pb-2 overflow-x-auto scrollbar-none whitespace-nowrap flex-shrink-0">
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
          <div className="flex-1 overflow-y-auto pr-3 scrollbar-thin min-h-0">
            {docLoading ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-500 gap-2">
                <div className="animate-spin h-6 w-6 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
                <span>{t('nav.loading_docs')}</span>
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
