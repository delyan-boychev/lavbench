import React, { useEffect } from 'react';
import { Outlet, Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../AuthContext';
import Navbar from './Navbar';
import CompetitionBar from './CompetitionBar';

export default function ProtectedLayout() {
  const { t } = useTranslation();
  const { currentUser, authLoading } = useAuth();
  const location = useLocation();

  if (authLoading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        minHeight: '100vh', background: 'var(--bg-base)',
      }}>
        <div style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          <div className="animate-spin" style={{
            width: 28, height: 28, border: '2px solid var(--border)',
            borderTopColor: 'var(--accent)', borderRadius: '50%',
            margin: '0 auto 12px',
          }} />
          <p style={{ fontSize: '0.8rem' }}>{t('common.loading')}</p>
        </div>
      </div>
    );
  }

  if (!currentUser) return <Navigate to="/login" replace />;

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)' }}>
      <Navbar />
      <CompetitionBar />
      <main style={{
        flex: 1,
        maxWidth: 1400,
        width: '100%',
        margin: '0 auto',
        padding: '20px 16px',
      }}>
        <div key={location.pathname} className="animate-fadein">
          <Outlet />
        </div>
      </main>
      <footer style={{
        borderTop: '1px solid var(--border)',
        padding: '16px 24px',
        textAlign: 'center',
        fontSize: '0.75rem',
        color: 'var(--text-muted)',
        background: 'var(--bg-surface)',
      }}>
        {t('common.footer')}
      </footer>
    </div>
  );
}
