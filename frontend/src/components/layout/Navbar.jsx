import React from 'react';
import api from '../../services/ApiService';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Logo from '../ui/Logo';
import Badge from '../ui/Badge';
import Modal from '../ui/Modal';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '../ui/MarkdownComponents';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import CountdownTimer from './CountdownTimer';
import { Sun, Moon, BookOpen, X, Menu, LogOut } from 'lucide-react';

function SunIcon() {
  return <Sun size={15} />;
}

function MoonIcon() {
  return <Moon size={15} />;
}

export default function Navbar() {
  const { currentUser, logout } = useAuth();
  const { theme, toggleTheme, showToast, selectedChallenge } = useApp();
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const [workerStatus, setWorkerStatus] = React.useState('online');
  const [clusters, setClusters] = React.useState([]);
  const [isModalOpen, setIsModalOpen] = React.useState(false);
  const [isDocsModalOpen, setIsDocsModalOpen] = React.useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);
  const [isNarrow, setIsNarrow] = React.useState(window.innerWidth <= 450);
  const [activeDocTab, setActiveDocTab] = React.useState('competitor');
  const [docContent, setDocContent] = React.useState('');
  const [docLoading, setDocLoading] = React.useState(false);
  const [docError, setDocError] = React.useState(null);
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setMobileMenuOpen(false);
    }, 0);
    return () => clearTimeout(timer);
  }, [location.pathname]);

  const docTabs = React.useMemo(() => {
    const tabs = [{ id: 'competitor', label: t('nav.doc_competitor_guide') }];
    if (currentUser?.role === 'jury' || currentUser?.role === 'admin') {
      tabs.push({ id: 'jury', label: t('nav.doc_jury_guide') });
    }
    if (currentUser?.role === 'admin') {
      tabs.push({ id: 'admin', label: t('nav.doc_admin_guide') });
    }
    return tabs;
  }, [currentUser, t]);

  React.useEffect(() => {
    if (!isDocsModalOpen) return;

    const fetchDoc = async () => {
      setDocLoading(true);
      setDocError(null);
      try {
        /** @type {Response} */
        const res = await api.fetch(`/api/docs/${activeDocTab}?lang=${i18n.language || 'en'}`, {
          headers: {
            'Accept-Language': i18n.language || 'en',
          },
        });
        if (res.ok) {
          const data = await res.json();
          setDocContent(data.content);
        } else {
          const errData = await res.json();
          setDocError(
            errData.code
              ? t(`api.${errData.code}`, errData.error || t('nav.failed_fetch_docs'))
              : errData.error || t('nav.failed_fetch_docs'),
          );
        }
      } catch {
        setDocError(t('nav.failed_fetch_docs_network'));
      } finally {
        setDocLoading(false);
      }
    };

    fetchDoc();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDocsModalOpen, activeDocTab]);

  const handleLogout = () => {
    logout();
    showToast(t('nav.signed_out_success'));
  };

  React.useEffect(() => {
    const eventSource = new EventSource('/api/worker-status/live');

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setWorkerStatus(data.status);
        setClusters(data.clusters || []);
      } catch {
        /* noop */
      }
    };

    eventSource.onerror = () => {
      setWorkerStatus('offline');
      setClusters([]);
    };

    return () => eventSource.close();
  }, []);

  React.useEffect(() => {
    const mq = window.matchMedia('(max-width: 450px)');
    const handler = (e) => setIsNarrow(e.matches);
    mq.addEventListener('change', handler);
    setIsNarrow(mq.matches); // eslint-disable-line react-hooks/set-state-in-effect
    return () => mq.removeEventListener('change', handler);
  }, []);

  const displayName = currentUser?.name?.trim()
    ? `${currentUser.name} ${currentUser.surname || ''}`.trim()
    : currentUser?.username;

  return (
    <header
      style={{
        background: 'var(--bg-nav)',
        borderBottom: '1px solid var(--border)',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
      }}
    >
      <div
        style={{
          maxWidth: 1400,
          margin: '0 auto',
          padding: '0 12px',
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
        }}
      >
        {/* Left: Logo */}
        <Logo size="lg" />

        {/* Center: Timer + Cluster + Docs (hidden on mobile) */}
        <div className="hidden lg:flex" style={{ gap: 10, alignItems: 'center' }}>
          <CountdownTimer selectedChallenge={selectedChallenge} />
          <button
            onClick={() => setIsModalOpen((prev) => !prev)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 12px',
              background:
                workerStatus === 'online' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
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
            <span
              style={{
                position: 'relative',
                display: 'flex',
                width: 8,
                height: 8,
              }}
            >
              {workerStatus === 'online' && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              )}
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${workerStatus === 'online' ? 'bg-emerald-500' : 'bg-rose-500'}`}
              ></span>
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
              <BookOpen size={13} strokeWidth={2.5} />
              {t('nav.docs')}
            </button>
          )}
        </div>

        {/* Right: user + controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {/* User info (mobile — name / role / alias; hidden under 450px) */}
          {currentUser && !isNarrow && (
            <div
              className="flex lg:hidden"
              style={{ flexDirection: 'column', alignItems: 'flex-end', gap: 2, padding: '2px 0' }}
            >
              <span
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  lineHeight: 1.2,
                }}
              >
                {displayName}
              </span>
              <Badge status={currentUser.role} />
              <span
                style={{
                  fontSize: '0.65rem',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                  lineHeight: 1.2,
                }}
              >
                {currentUser.alias_id}
              </span>
            </div>
          )}

          {/* User info (desktop) */}
          {currentUser && (
            <div
              className="hidden lg:flex"
              style={{ flexDirection: 'column', alignItems: 'flex-end', gap: 2, padding: '2px 0' }}
            >
              <span
                style={{
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  lineHeight: 1.2,
                }}
              >
                {displayName}
              </span>
              <Badge status={currentUser.role} />
              <span
                style={{
                  fontSize: '0.65rem',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                  lineHeight: 1.2,
                }}
              >
                {currentUser.alias_id}
              </span>
            </div>
          )}

          {/* Mobile menu toggle */}
          <button
            className="flex lg:hidden"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-secondary)',
              width: 32,
              height: 32,
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              flexShrink: 0,
            }}
          >
            {mobileMenuOpen ? <X size={16} /> : <Menu size={16} />}
          </button>

          {/* Language toggle */}
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
              width: 32,
              height: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              userSelect: 'none',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--text-primary)';
              e.currentTarget.style.borderColor = 'var(--border-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--text-secondary)';
              e.currentTarget.style.borderColor = 'var(--border)';
            }}
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
              width: 32,
              height: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--text-primary)';
              e.currentTarget.style.borderColor = 'var(--border-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--text-secondary)';
              e.currentTarget.style.borderColor = 'var(--border)';
            }}
          >
            {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
          </button>

          {/* Logout (desktop — icon only) */}
          <button
            onClick={handleLogout}
            className="hidden lg:inline-flex"
            title={t('nav.sign_out')}
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-secondary)',
              width: 32,
              height: 32,
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              flexShrink: 0,
            }}
          >
            <LogOut size={15} />
          </button>
        </div>
      </div>

      {/* Mobile dropdown menu */}
      {mobileMenuOpen && (
        <div
          className="flex lg:hidden"
          style={{
            background: 'var(--bg-nav)',
            borderTop: '1px solid var(--border)',
            padding: '12px 12px',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          {currentUser && (
            <div style={{ padding: '4px 8px', textAlign: 'center' }}>
              {isNarrow ? (
                <div
                  style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}
                >
                  <span
                    style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}
                  >
                    {displayName}
                  </span>
                  <Badge status={currentUser.role} />
                  <span
                    style={{
                      fontSize: '0.78rem',
                      color: 'var(--text-muted)',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {currentUser.alias_id}
                  </span>
                </div>
              ) : (
                <>
                  <div
                    style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}
                  >
                    {displayName}
                  </div>
                  <span
                    style={{
                      fontSize: '0.78rem',
                      color: 'var(--text-muted)',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {currentUser.alias_id}
                  </span>
                </>
              )}
            </div>
          )}
          <CountdownTimer selectedChallenge={selectedChallenge} />
          <button
            onClick={() => {
              setIsModalOpen(true);
              setMobileMenuOpen(false);
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 14px',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.85rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
              cursor: 'pointer',
              width: '100%',
              justifyContent: 'center',
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: workerStatus === 'online' ? '#10b981' : '#ef4444',
              }}
            ></span>
            {t('nav.cluster')}
          </button>
          {currentUser && (
            <button
              onClick={() => {
                setIsDocsModalOpen(true);
                setMobileMenuOpen(false);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '10px 14px',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.85rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                cursor: 'pointer',
                width: '100%',
                justifyContent: 'center',
              }}
            >
              <BookOpen size={14} />
              {t('nav.docs')}
            </button>
          )}
          <button
            onClick={handleLogout}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 14px',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.85rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
              cursor: 'pointer',
              width: '100%',
              justifyContent: 'center',
            }}
          >
            <LogOut size={14} />
            {t('nav.sign_out')}
          </button>
        </div>
      )}

      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={t('nav.cluster_info_title')}
        size="md"
        footer={
          <button className="btn btn-secondary btn-sm px-4" onClick={() => setIsModalOpen(false)}>
            {t('nav.close')}
          </button>
        }
      >
        <div className="flex flex-col gap-4 text-xs text-left">
          <p className="text-slate-400">{t('nav.cluster_info_desc')}</p>

          {/* Cluster Status Summary Info Card */}
          <div className="bg-slate-950/60 border border-indigo-500/10 p-4 rounded-xl flex flex-col gap-2">
            <h4 className="font-bold text-slate-200 text-xs uppercase tracking-wider mb-1 text-indigo-400">
              {t('nav.cluster_status_summary')}
            </h4>
            <div className="flex flex-col gap-2.5 text-slate-300">
              <div className="flex justify-between items-center border-b border-white/5 pb-1.5">
                <span className="text-slate-400">{t('nav.system_status')}</span>
                <span className="font-bold text-emerald-400">{t('nav.active')}</span>
              </div>
              <div className="flex justify-between items-center border-b border-white/5 pb-1.5">
                <span className="text-slate-400">{t('nav.total_nodes')}</span>
                <span className="font-bold text-slate-100">{clusters.length}</span>
              </div>
              <div className="flex justify-between items-center border-b border-white/5 pb-1.5">
                <span className="text-slate-400">{t('nav.global_concurrency')}</span>
                <span className="font-bold text-slate-100 text-right">
                  {t('nav.global_parallel_tasks', {
                    count: clusters.reduce((acc, c) => acc + (c.concurrency || 0), 0),
                  })}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">{t('nav.resource_routing')}</span>
                <span className="font-bold text-indigo-400 text-right">
                  {t('nav.auto_load_balanced')}
                </span>
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
                <div
                  key={cluster.name || idx}
                  className="bg-slate-950/40 border border-white/5 p-4 rounded-xl flex flex-col gap-3"
                >
                  <div className="flex justify-between items-center">
                    <span className="font-mono text-indigo-400 font-bold text-sm">
                      {cluster.name}
                    </span>
                    <span
                      className={`px-2 py-0.5 text-[9px] font-bold rounded-full border ${
                        cluster.type === 'GPU'
                          ? 'bg-indigo-500/10 border-indigo-500/20 text-indigo-400'
                          : 'bg-slate-800 border-slate-700 text-slate-300'
                      }`}
                    >
                      {t('nav.node_type', { type: cluster.type })}
                    </span>
                  </div>

                  <div className="flex flex-col gap-2.5 text-slate-300 font-medium text-xs">
                    <div className="flex justify-between items-center border-b border-white/5 pb-1.5">
                      <span className="text-slate-500 font-semibold">{t('nav.concurrency')}</span>
                      <span className="font-bold text-slate-200">
                        {t('nav.parallel_tasks', { count: cluster.concurrency })}
                      </span>
                    </div>
                    <div className="flex justify-between items-center border-b border-white/5 pb-1.5">
                      <span className="text-slate-500 font-semibold">{t('nav.ram_limit')}</span>
                      <span className="font-bold text-slate-200">{cluster.ram_gb} GB</span>
                    </div>
                    <div className="flex justify-between items-center border-b border-white/5 pb-1.5">
                      <span className="text-slate-500 font-semibold">{t('nav.gpu_model')}</span>
                      <span
                        className="font-bold text-slate-200 truncate max-w-[220px] text-right"
                        title={cluster.gpu_type}
                      >
                        {cluster.gpu_type}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500 font-semibold">{t('nav.vram_limit')}</span>
                      <span className="font-bold text-slate-200">
                        {cluster.vram_gb !== 'N/A' && cluster.vram_gb !== null
                          ? `${cluster.vram_gb} GB`
                          : 'N/A'}
                      </span>
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
        footer={
          <button
            className="btn btn-secondary btn-sm px-4"
            onClick={() => setIsDocsModalOpen(false)}
          >
            {t('nav.close')}
          </button>
        }
      >
        <div className="flex flex-col gap-4 text-left flex-1 min-h-0">
          {/* Tabs header - scrollable horizontally on small viewports */}
          {docTabs.length > 1 && (
            <div className="flex gap-2 border-b border-white/5 pb-2 overflow-x-auto scrollbar-none whitespace-nowrap flex-shrink-0">
              {docTabs.map((tab) => (
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
