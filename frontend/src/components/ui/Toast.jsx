import React from 'react';

export default function Toast({ toast }) {
  if (!toast?.show) return null;
  const isError = toast.type === 'error' || toast.type === 'danger';
  return (
    <div className={`fixed bottom-6 right-6 flex items-center gap-3 bg-slate-900 border border-white/10 p-4 rounded-lg shadow-2xl z-50 transition-all duration-300 ${isError ? 'border-l-4 border-l-rose-500' : 'border-l-4 border-l-indigo-600'}`}>
      <div className={`h-2 w-2 rounded-full ${isError ? 'bg-rose-500' : 'bg-emerald-500'}`}></div>
      <span className="text-sm font-semibold text-slate-100">{toast.message}</span>
    </div>
  );
}
