import React from 'react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Logo from '../ui/Logo';
import Badge from '../ui/Badge';
import Modal from '../ui/Modal';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router';
import CountdownTimer from './CountdownTimer';
import { useDocsQuery } from '../../hooks/useDocsQuery';
import { Sun, Moon, BookOpen, X, Menu, LogOut } from 'lucide-react';

const DocsMarkdown = React.lazy(() => import('./DocsMarkdown'));

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
  const [isDocsModalOpen, setIsDocsModalOpen] = React.useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);
  const [isNarrow, setIsNarrow] = React.useState(window.innerWidth <= 450);
  const [activeDocTab, setActiveDocTab] = React.useState('competitor');

  const {
    data: docData,
    isLoading: docLoading,
    error: docError,
  } = useDocsQuery(
    isDocsModalOpen ? activeDocTab : null,
    isDocsModalOpen ? i18n.language || 'en' : null,
  );
  const docContent = docData?.content || '';

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

  const handleLogout = () => {
    logout();
    showToast(t('nav.signed_out_success'));
  };

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
        <Logo size={isNarrow ? 'md' : 'lg'} />

        {/* Center: Timer + Docs (hidden on mobile) */}
        <div className="hidden lg:flex" style={{ gap: 10, alignItems: 'center' }}>
          <CountdownTimer selectedChallenge={selectedChallenge} />
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          {/* User info (mobile — name / role / alias; hidden under 450px) */}
          {currentUser && !isNarrow && (
            <div
              className="flex lg:hidden min-w-0 max-w-[40vw] sm:max-w-[220px]"
              style={{ flexDirection: 'column', alignItems: 'flex-end', gap: 2, padding: '2px 0' }}
            >
              <span
                className="truncate max-w-full"
                title={displayName}
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
                className="truncate max-w-full"
                title={currentUser.alias_id}
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
            type="button"
            className="flex lg:hidden"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            aria-label={mobileMenuOpen ? t('nav.close_menu') : t('nav.open_menu')}
            aria-expanded={mobileMenuOpen}
            aria-controls="mobile-nav-menu"
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
          id="mobile-nav-menu"
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
                {docError?.message || t('nav.failed_fetch_docs')}
              </div>
            ) : (
              <div className="prose prose-invert max-w-none text-slate-300">
                <React.Suspense fallback={null}>
                  <DocsMarkdown content={docContent} />
                </React.Suspense>
              </div>
            )}
          </div>
        </div>
      </Modal>
    </header>
  );
}
