import React from 'react';
import { withTranslation } from 'react-i18next';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  render() {
    const { t } = this.props;
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '60vh',
              padding: '40px 20px',
              textAlign: 'center',
              color: 'var(--text-primary)',
            }}
          >
            <svg
              width="48"
              height="48"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="1.5"
              style={{ color: 'var(--danger, #ef4444)', marginBottom: 16 }}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
              />
            </svg>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: 8 }}>
              {t('common.something_went_wrong', 'Something went wrong')}
            </h2>
            <p
              style={{
                fontSize: '0.875rem',
                color: 'var(--text-muted)',
                maxWidth: 400,
                lineHeight: 1.5,
              }}
            >
              {t(
                'common.unexpected_error',
                'An unexpected error occurred. Please try refreshing the page.',
              )}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              style={{
                marginTop: 20,
                padding: '8px 20px',
                background: 'var(--accent, #6366f1)',
                color: '#fff',
                border: 'none',
                borderRadius: 'var(--radius-sm, 6px)',
                fontSize: '0.875rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {t('common.refresh_page', 'Refresh Page')}
            </button>
          </div>
        )
      );
    }

    return this.props.children;
  }
}

export default withTranslation()(ErrorBoundary);
