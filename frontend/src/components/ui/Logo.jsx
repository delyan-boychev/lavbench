import React from 'react';
import { useApp } from '../../context/AppContext';

export default function Logo({ size = 'md' }) {
  const { theme } = useApp();
  const textSize = size === 'sm' ? '0.95rem' : size === 'lg' ? '1.4rem' : '1.1rem';

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, userSelect: 'none' }}>
      {/* Icon mark */}
      <svg width={size === 'sm' ? 22 : 28} height={size === 'sm' ? 22 : 28} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="var(--accent)" opacity="0.9" />
        <path d="M7 14L14 7L21 14L14 21L7 14Z" fill="white" opacity="0.9" />
        <circle cx="14" cy="14" r="3.5" fill="white" />
      </svg>
      {/* Wordmark */}
      <span style={{
        fontSize: textSize,
        fontWeight: 700,
        letterSpacing: '-0.02em',
        color: 'var(--text-primary)',
      }}>
        NAI
        <span style={{
          fontWeight: 400,
          color: 'var(--text-secondary)',
          marginLeft: 4,
          fontSize: `calc(${textSize} * 0.85)`,
        }}>Platform</span>
      </span>
    </div>
  );
}
