import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import InputField from '../components/ui/InputField';
import Button from '../components/ui/Button';

export default function Login() {
  const { token, currentUser, login, authError, setAuthError } = useAuth();
  const navigate = useNavigate();

  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [isAdminLogin, setIsAdminLogin] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // If already authenticated, redirect to home
    if (token && currentUser) {
      navigate('/challenges', { replace: true });
    }
  }, [token, currentUser, navigate]);

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
    <div className="flex items-center justify-center min-h-screen p-6 bg-slate-950">
      
      <div className="bg-slate-900 border border-slate-800/80 p-8 max-w-[440px] w-full rounded-xl shadow-xl">
        
        <div className="text-center mb-8">
          <div className="flex flex-col items-center gap-2.5">
            <h1 className="text-2xl font-bold text-white tracking-tight">
              National AI Competition
            </h1>
            <span className="bg-indigo-500/15 border border-indigo-500/30 text-indigo-400 text-[10px] tracking-wider uppercase font-bold px-2.5 py-0.5 rounded">
              Platform
            </span>
          </div>
          <p className="text-slate-400 text-xs mt-2">
            Sign in to access your dashboard
          </p>
        </div>

        {authError && (
          <div className="bg-rose-500/10 border border-rose-500/30 text-rose-400 px-4 py-3 rounded-lg text-xs mb-6">
            {authError}
          </div>
        )}

        <form onSubmit={handleAuth} className="flex flex-col gap-4">
          <div className="flex items-center gap-2.5 mb-2">
            <input 
              type="checkbox" 
              id="admin-login-check" 
              checked={isAdminLogin}
              onChange={(e) => {
                setIsAdminLogin(e.target.checked);
                setAuthEmail('');
                setAuthPassword('');
                setAuthError('');
              }}
              className="accent-indigo-600 h-4 w-4 cursor-pointer"
            />
            <label htmlFor="admin-login-check" className="text-xs font-semibold text-slate-300 cursor-pointer select-none">
              Sign In as Administrator (Requires Master Key)
            </label>
          </div>

          <InputField
            label={isAdminLogin ? "Admin Username" : "Username or Email Address"}
            value={authEmail}
            onChange={(e) => setAuthEmail(e.target.value)}
            placeholder={isAdminLogin ? "admin_xxxxxx" : "comp_ali_lov_3812 or jury@competition.ai"}
            required
            disabled={loading}
          />

          {isAdminLogin ? (
            <InputField
              label="Master Admin Key"
              type="password"
              value={authPassword}
              onChange={(e) => setAuthPassword(e.target.value)}
              placeholder="admin_key_..."
              required
              disabled={loading}
            />
          ) : (
            <InputField
              label="Password"
              type="password"
              value={authPassword}
              onChange={(e) => setAuthPassword(e.target.value)}
              placeholder="••••••••"
              required
              disabled={loading}
            />
          )}

          <Button type="submit" variant="primary" className="w-full mt-2" disabled={loading}>
            {loading ? "Signing In..." : "Sign In"}
          </Button>
        </form>
        
      </div>
    </div>
  );
}
