import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import api from './services/ApiService';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const queryClient = useQueryClient();
  const [currentUser, setCurrentUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');
  const [authCheckError, setAuthCheckError] = useState(false);

  const clearSession = useCallback(() => {
    setCurrentUser(null);
    setAuthLoading(false);
    setAuthCheckError(false);
    queryClient.clear();
  }, [queryClient]);

  const logout = useCallback(async () => {
    clearSession();
    /** @type {Promise<{ ok: boolean, data: import('./types/api').paths['/api/auth/logout']['post']['responses']['200']['content']['application/json'] }>} */
    try {
      await api.post('/auth/logout');
    } catch {
      /* ignore network errors on logout */
    }
  }, [clearSession]);

  // Listen for global unauthorized events from ApiService
  useEffect(() => {
    const handleUnauthorized = () => {
      clearSession();
    };
    window.addEventListener('auth:unauthorized', handleUnauthorized);
    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized);
    };
  }, [clearSession]);

  // Fetch current user details
  const fetchUser = useCallback(async () => {
    setAuthLoading(true);
    setAuthCheckError(false);
    try {
      /** @type {{ ok: boolean, status: number, data: import('./types/api').paths['/api/auth/me']['get']['responses']['200']['content']['application/json'] }} */
      const { ok, status, data } = await api.get('/auth/me');
      if (ok) {
        setCurrentUser(data.user);
      } else if (status === 401) {
        clearSession();
      } else {
        setAuthCheckError(true);
      }
    } catch {
      setAuthCheckError(true);
    } finally {
      setAuthLoading(false);
    }
  }, [clearSession]);

  const login = async (identifier, password) => {
    setAuthError('');
    try {
      let finalPassword = password || '';

      const { ok, data } = await api.post('/auth/login', {
        username: (identifier || '').trim(),
        password: finalPassword,
      });

      if (ok) {
        setCurrentUser(data.user);
        setAuthCheckError(false);
        await api.refreshCsrfToken();
        return { success: true };
      } else {
        setAuthError(
          /** @type {string} */ (
            data?.code ? { code: data.code, error: data.error } : 'auth.failed'
          ),
        );
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
    <AuthContext.Provider
      value={{
        currentUser,
        authLoading,
        authError,
        authCheckError,
        login,
        logout,
        setAuthError,
        fetchUser,
      }}
    >
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
