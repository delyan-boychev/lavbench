import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from '../AuthContext';

const AppContext = createContext(null);

export const AppProvider = ({ children }) => {
  const { token } = useAuth();
  const [challenges, setChallenges] = useState([]);
  const [selectedChallenge, setSelectedChallengeState] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);
  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'dark');
  const [toast, setToast] = useState({ show: false, message: '', type: 'success' });

  // Apply theme to <html> element
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(prev => prev === 'dark' ? 'light' : 'dark');

  const showToast = useCallback((message, type = 'success') => {
    setToast({ show: true, message, type });
    setTimeout(() => setToast({ show: false, message: '', type: 'success' }), 4000);
  }, []);

  const fetchChallenges = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch('/api/challenges', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setChallenges(data);
        if (data.length > 0) {
          setSelectedChallengeState(prev => {
            const keep = prev ? data.find(c => c.id === prev.id) : null;
            const next = keep || data[0];
            // Reset task if challenge changed or task no longer exists
            setSelectedTask(t => {
              if (!t) return next.tasks?.[0] || null;
              const found = next.tasks?.find(tk => tk.id === t.id);
              return found || next.tasks?.[0] || null;
            });
            return next;
          });
        } else {
          setSelectedChallengeState(null);
          setSelectedTask(null);
        }
      }
    } catch (e) {
      console.error('fetchChallenges error:', e);
    }
  }, [token]);

  // Fetch challenges when user logs in
  useEffect(() => {
    if (token) fetchChallenges();
    else { setChallenges([]); setSelectedChallengeState(null); setSelectedTask(null); }
  }, [token, fetchChallenges]);

  // Set selected challenge by ID - resets task to first of new challenge (fixes B7)
  const setSelectedChallengeById = useCallback((id) => {
    const c = challenges.find(ch => ch.id === id);
    if (c) {
      setSelectedChallengeState(c);
      setSelectedTask(c.tasks?.[0] || null);
    }
  }, [challenges]);

  return (
    <AppContext.Provider value={{
      challenges,
      selectedChallenge,
      setSelectedChallengeById,
      setSelectedChallenge: setSelectedChallengeState,
      selectedTask,
      setSelectedTask,
      theme,
      toggleTheme,
      toast,
      showToast,
      fetchChallenges,
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
};
