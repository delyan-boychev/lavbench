import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from './services/ApiService';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [currentUser, setCurrentUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');

  const logout = useCallback(async () => {
    /** @type {Promise<{ ok: boolean, data: import('./types/api').paths['/api/auth/logout']['post']['responses']['200']['content']['application/json'] }>} */
    try { await api.post('/auth/logout'); } catch { /* ignore network errors on logout */ }
    setCurrentUser(null);
    setAuthLoading(false);
  }, []);

  // Listen for global unauthorized events from ApiService
  useEffect(() => {
    const handleUnauthorized = () => {
      logout();
    };
    window.addEventListener('auth:unauthorized', handleUnauthorized);
    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized);
    };
  }, [logout]);

  // Fetch current user details
  const fetchUser = useCallback(async () => {
    setAuthLoading(true);
    try {
      /** @type {{ ok: boolean, data: import('./types/api').paths['/api/auth/me']['get']['responses']['200']['content']['application/json'] }} */
      const { ok, data } = await api.get('/auth/me');
      if (ok) {
        setCurrentUser(data.user);
      } else {
        setCurrentUser(null);
      }
    } catch {
      setCurrentUser(null);
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const login = async (identifier, password) => {
    setAuthError('');
    try {
      let finalPassword = password || '';
      
      const { ok, data } = await api.post('/auth/login', { 
        username: (identifier || '').trim(), 
        password: finalPassword 
      });
      
      if (ok) {
        setCurrentUser(data.user);
        await api.refreshCsrfToken();
        return { success: true };
      } else {
        setAuthError(/** @type {string} */(data?.code ? { code: data.code, error: data.error } : 'auth.failed'));
        return { success: false, error: data?.error };
      }
    } catch {
      setAuthError('auth.unreachable');
      return { success: false, error: 'auth.network_error' };
    }
  };

  // On mount: check if there's an active session via cookie and refresh CSRF token
  useEffect(() => {
    fetchUser(); // eslint-disable-line react-hooks/set-state-in-effect
    api.refreshCsrfToken();
  }, [fetchUser]);

  return (
    <AuthContext.Provider value={{
      currentUser,
      authLoading,
      authError,
      login,
      logout,
      setAuthError,
      fetchUser
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
