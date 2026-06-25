import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider, useApp } from './context/AppContext';
import ErrorBoundary from './components/ErrorBoundary';
import ProtectedLayout from './components/layout/ProtectedLayout';
import Login from './pages/Login';
import Home from './pages/Home';
import LeaderboardView from './pages/LeaderboardView';
import LeaderboardDemo from './pages/LeaderboardDemo';

const AdminPanel = lazy(() => import('./pages/AdminPanel'));
const SubmissionsView = lazy(() => import('./pages/SubmissionsView'));

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center min-h-[400px]">
      <div className="animate-spin h-6 w-6 border-2 border-slate-700 border-t-indigo-500 rounded-full" />
    </div>
  );
}

function ToastContainer() {
  const { toast } = useApp();
  if (!toast?.show) return null;

  return (
    <div
      className={`fixed bottom-6 right-6 flex items-center gap-3 bg-slate-900 border border-white/10 p-4 rounded-lg shadow-2xl z-[200] transition-all duration-300 ${toast.type === 'rose' || toast.type === 'error' ? 'border-l-4 border-l-rose-500' : 'border-l-4 border-l-indigo-600'}`}
    >
      <div
        className={`h-2 w-2 rounded-full ${toast.type === 'rose' || toast.type === 'error' ? 'bg-rose-500' : 'bg-emerald-500'}`}
      ></div>
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
              <Route
                path="/submissions"
                element={
                  <Suspense fallback={<LoadingFallback />}>
                    <SubmissionsView />
                  </Suspense>
                }
              />
              <Route
                path="/challenges/:challengeId/submissions"
                element={
                  <Suspense fallback={<LoadingFallback />}>
                    <SubmissionsView />
                  </Suspense>
                }
              />
              <Route
                path="/admin"
                element={
                  <Suspense fallback={<LoadingFallback />}>
                    <AdminPanel />
                  </Suspense>
                }
              />
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
