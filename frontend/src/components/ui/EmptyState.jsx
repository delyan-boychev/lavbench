import React from 'react';

export default function EmptyState({ icon = null, message, minHeight = 200, surface = true, children = null }) {
  const minHeightVal = typeof minHeight === 'number' ? `${minHeight}px` : minHeight;

  return (
    <div 
      className={`${surface ? 'surface' : ''} empty-state`} 
      style={{ minHeight: minHeightVal }}
    >
      {icon && (
        <div style={{ color: 'var(--text-muted)' }}>
          {icon}
        </div>
      )}
      {message && <p>{message}</p>}
      {children}
    </div>
  );
}
