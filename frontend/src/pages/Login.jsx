import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import { useTranslation } from 'react-i18next';
import InputField from '../components/ui/InputField';
import Button from '../components/ui/Button';
import Logo from '../components/ui/Logo';
import { Sun, Moon } from 'lucide-react';

function SunIcon() {
  return <Sun size={15} />;
}

function MoonIcon() {
  return <Moon size={15} />;
}

export default function Login() {
  const { currentUser, login, authError } = useAuth();
  const { theme, toggleTheme } = useApp();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();

  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // If already authenticated, redirect to home
    if (currentUser) {
      navigate('/challenges', { replace: true });
    }
  }, [currentUser, navigate]);

  const handleAuth = async (e) => {
    e.preventDefault();
    setLoading(true);
    const result = await login(authEmail, authPassword);
    setLoading(false);
    if (result.success) {
      setAuthPassword('');
      navigate('/challenges', { replace: true });
    }
  };

  return (
    <div className="relative flex items-center justify-center min-h-screen p-6 bg-slate-950">
      {/* Top right language and theme selectors */}
      <div className="absolute top-6 right-6 flex items-center gap-2.5 z-50">
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
      </div>

      <div className="bg-slate-900 border border-slate-800/80 p-8 max-w-[440px] w-full rounded-xl shadow-xl">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-5">
            <Logo size="xl" />
          </div>
        </div>

        {authError && (
          <div className="bg-rose-500/10 border border-rose-500/30 text-rose-400 px-4 py-3 rounded-lg text-xs mb-6">
            {
              /** @type {React.ReactNode} */ (
                typeof authError === 'object'
                  ? t(`api.${authError.code}`, authError.error)
                  : t(authError)
              )
            }
          </div>
        )}

        <form onSubmit={handleAuth} className="flex flex-col gap-4">
          <InputField
            label={t('auth.email_username')}
            value={authEmail}
            onChange={(e) => setAuthEmail(e.target.value)}
            placeholder={t('auth.username_placeholder')}
            required
            disabled={loading}
          />

          <InputField
            label={t('auth.password')}
            type="password"
            value={authPassword}
            onChange={(e) => setAuthPassword(e.target.value)}
            placeholder="••••••••"
            required
            disabled={loading}
          />

          <Button type="submit" variant="primary" className="w-full mt-2" disabled={loading}>
            {loading ? t('auth.signing_in') : t('auth.sign_in')}
          </Button>
        </form>
      </div>
    </div>
  );
}
