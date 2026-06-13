import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

const AuthContext = createContext(null);
const API_BASE = '/api';

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

  // Fetch current user details
  const fetchUser = useCallback(async (currentToken) => {
    if (!currentToken) {
      setCurrentUser(null);
      setAuthLoading(false);
      return;
    }
    setAuthLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: { 'Authorization': `Bearer ${currentToken}` }
      });
      if (res.ok) {
        const data = await res.json();
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
      if (finalPassword.startsWith('admin_key_')) {
        finalPassword = finalPassword.trim();
      }
      const hashedPassword = await hashPassword(finalPassword);
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: (identifier || '').trim(), password: hashedPassword })
      });
      const data = await res.json();
      if (res.ok) {
        setToken(data.token);
        localStorage.setItem('token', data.token);
        setCurrentUser(data.user);
        return { success: true };
      } else {
        setAuthError(data.error || 'Authentication failed.');
        return { success: false, error: data.error };
      }
    } catch (err) {
      setAuthError('Unable to reach the server.');
      return { success: false, error: 'Network error.' };
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
