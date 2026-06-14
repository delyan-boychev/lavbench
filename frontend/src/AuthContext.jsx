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
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [currentUser, setCurrentUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');

  // Logout function
  const logout = useCallback(() => {
    setToken('');
    setCurrentUser(null);
    localStorage.removeItem('token');
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
  const fetchUser = useCallback(async (currentToken) => {
    if (!currentToken) {
      setCurrentUser(null);
      setAuthLoading(false);
      return;
    }
    setAuthLoading(true);
    try {
      // Temporarily store token in localStorage if it isn't so ApiService can use it
      if (!localStorage.getItem('token')) {
        localStorage.setItem('token', currentToken);
      }
      const { ok, data } = await api.get('/auth/me');
      if (ok) {
        if (currentToken === localStorage.getItem('token')) {
          setCurrentUser(data.user);
        }
      } else {
        if (currentToken === localStorage.getItem('token')) {
          logout();
        }
      }
    } catch (e) {
      console.error('Error fetching user info:', e);
    } finally {
      setAuthLoading(false);
    }
  }, [logout]);

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
        setToken(data.token);
        localStorage.setItem('token', data.token);
        setCurrentUser(data.user);
        return { success: true };
      } else {
        setAuthError(data?.code ? { code: data.code, error: data.error } : 'auth.failed');
        return { success: false, error: data?.error };
      }
    } catch (err) {
      setAuthError('auth.unreachable');
      return { success: false, error: 'auth.network_error' };
    }
  };

  // Sync token changes to localStorage and load user profile
  useEffect(() => {
    if (token) {
      localStorage.setItem('token', token);
      if (!currentUser) {
        fetchUser(token);
      } else {
        setAuthLoading(false);
      }
    } else {
      localStorage.removeItem('token');
      setCurrentUser(null);
      setAuthLoading(false);
    }
  }, [token, fetchUser, currentUser]);

  return (
    <AuthContext.Provider value={{
      token,
      currentUser,
      authLoading,
      authError,
      login,
      logout,
      setAuthError,
      fetchUser: () => fetchUser(token)
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
