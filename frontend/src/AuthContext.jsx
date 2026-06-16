import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from './services/ApiService';

const AuthContext = createContext(null);

// Native browser Web Crypto API SHA-256 hash helper
const hashPassword = async (password) => {
  const encoder = new TextEncoder();
  const data = encoder.encode(password);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
};

export const AuthProvider = ({ children }) => {
  const [currentUser, setCurrentUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');

  const logout = useCallback(async () => {
    try { await api.post('/auth/logout'); } catch {}
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
      const hashedPassword = await hashPassword(finalPassword);
      
      const { ok, data } = await api.post('/auth/login', { 
        username: (identifier || '').trim(), 
        password: hashedPassword 
      });
      
      if (ok) {
        setCurrentUser(data.user);
        return { success: true };
      } else {
        setAuthError(data?.code ? { code: data.code, error: data.error } : 'auth.failed');
        return { success: false, error: data?.error };
      }
    } catch {
      setAuthError('auth.unreachable');
      return { success: false, error: 'auth.network_error' };
    }
  };

  // On mount: check if there's an active session via cookie
  useEffect(() => {
    fetchUser();
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
