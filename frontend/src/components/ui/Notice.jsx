import React from 'react';

// One look for every inline notice box. The tone classes are the ones the light
// theme already overrides in index.css, so notices follow the theme
const TONES = {
  info: 'bg-slate-500/10 border-slate-500/20 text-slate-300',
  warning: 'bg-amber-500/10 border-amber-500/20 text-amber-300',
  error: 'bg-rose-500/10 border-rose-500/30 text-rose-400',
};

/**
 * @param {{ tone?: 'info' | 'warning' | 'error', role?: string, className?: string, children: React.ReactNode }} props
 */
export default function Notice({ tone = 'info', role, className = '', children }) {
  return (
    <div role={role} className={`px-4 py-3 border rounded-lg text-xs ${TONES[tone]} ${className}`}>
      {children}
    </div>
  );
}
