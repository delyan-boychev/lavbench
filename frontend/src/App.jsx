import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider, useApp } from './context/AppContext';
import ErrorBoundary from './components/ErrorBoundary';
import ProtectedLayout from './components/layout/ProtectedLayout';
import Login from './pages/Login';
import Home from './pages/Home';
import LeaderboardView from './pages/LeaderboardView';
import SubmissionsView from './pages/SubmissionsView';
import AdminPanel from './pages/AdminPanel';
import LeaderboardDemo from './pages/LeaderboardDemo';

function ToastContainer() {
  const { toast } = useApp();
  if (!toast?.show) return null;
  
  return (
    <div className={`fixed bottom-6 right-6 flex items-center gap-3 bg-slate-900 border border-white/10 p-4 rounded-lg shadow-2xl z-50 transition-all duration-300 ${toast.type === 'rose' || toast.type === 'error' ? 'border-l-4 border-l-rose-500' : 'border-l-4 border-l-indigo-600'}`}>
      <div className={`h-2 w-2 rounded-full ${toast.type === 'rose' || toast.type === 'error' ? 'bg-rose-500' : 'bg-emerald-500'}`}></div>
      <span className="text-sm font-semibold text-slate-100">{toast.message}</span>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <ErrorBoundary>
        <Routes>
          {/* Protected Routes */}
          <Route element={<ProtectedLayout />}>
            <Route path="/" element={<Navigate to="/challenges" replace />} />
            <Route path="/challenges" element={<Home />} />
            <Route path="/challenges/:challengeId" element={<Home />} />
            <Route path="/leaderboard" element={<LeaderboardView />} />
            <Route path="/challenges/:challengeId/leaderboard" element={<LeaderboardView />} />
            <Route path="/submissions" element={<SubmissionsView />} />
            <Route path="/challenges/:challengeId/submissions" element={<SubmissionsView />} />
            <Route path="/admin" element={<AdminPanel />} />
          </Route>
          
          {/* Public Login Route */}
          <Route path="/login" element={<Login />} />
          
          {/* Demo */}
          <Route path="/demo/leaderboard" element={<LeaderboardDemo />} />
          
          {/* Fallback Catch-all Route */}
          <Route path="*" element={<Navigate to="/challenges" replace />} />
        </Routes>
        </ErrorBoundary>
        <ToastContainer />
      </BrowserRouter>
    </AppProvider>
  );
}
