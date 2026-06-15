import React from 'react';

export default function Logo({ size = 'md' }) {
  const dims = { sm: 28, md: 38, lg: 48, xl: 64 };
  const s = dims[size] || dims.md;
  const textSize = size === 'xl' ? '2rem' : size === 'lg' ? '1.4rem' : size === 'sm' ? '0.85rem' : '1.05rem';

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, userSelect: 'none' }}>
      <svg width={s} height={s} viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Deep, premium slate background for high contrast */}
        <rect width="36" height="36" rx="8" fill="#0f172a" />
        
        {/* Mane strands — Redrawn with mathematically perfect Quadratic sweeping arcs */}
        <path d="M 18 11.5 L 18 6.5 
                 M 21.8 12.6 Q 25.1 11.3 23.7 8.0 
                 M 25.1 15.6 Q 28.6 15.6 28.6 12.1 
                 M 27.2 20.2 Q 30.5 21.5 31.8 18.3 
                 M 28 25.5 Q 30.5 28.0 33 25.5 
                 M 14.2 12.6 Q 10.9 11.3 12.3 8.0 
                 M 10.9 15.6 Q 7.4 15.6 7.4 12.1 
                 M 8.8 20.2 Q 5.5 21.5 4.2 18.3 
                 M 8 25.5 Q 5.5 28.0 3 25.5" 
          stroke="#f59e0b" strokeWidth="1.2" strokeLinecap="round" opacity="0.8" />
          
        {/* ML / Neural Network Nodes — Locked to the outer ellipse (rx=15, ry=19) */}
        <g fill="#f59e0b">
          <circle cx="18" cy="6.5" r="1.2" />       {/* 90° */}
          <circle cx="12.3" cy="8.0" r="1.2" />     {/* 112.5° */}
          <circle cx="23.7" cy="8.0" r="1.2" />     {/* 67.5° */}
          <circle cx="7.4" cy="12.1" r="1.2" />     {/* 135° */}
          <circle cx="28.6" cy="12.1" r="1.2" />    {/* 45° */}
          <circle cx="4.2" cy="18.3" r="1.2" />     {/* 157.5° */}
          <circle cx="31.8" cy="18.3" r="1.2" />    {/* 22.5° */}
          <circle cx="3" cy="25.5" r="1.2" />       {/* 180° */}
          <circle cx="33" cy="25.5" r="1.2" />      {/* 0° */}
        </g>
        
        {/* Arc — A perfect half-ellipse (rx=10, ry=14) anchoring the structure */}
        <path d="M 8 25.5 A 10 14 0 0 1 28 25.5" stroke="#f59e0b" strokeWidth="1.5" fill="none" />

        {/* Symmetric Outer bars — Centers locked exactly at x=8 and x=28 */}
        <rect x="6.5" y="25.5" width="3" height="4" rx="1.5" fill="#f59e0b" />
        <rect x="26.5" y="25.5" width="3" height="4" rx="1.5" fill="#f59e0b" />
        
        {/* Mid bars extended upwards — Centers locked exactly at x=13 and x=23 */}
        <g>
          <rect x="11.5" y="18.5" width="3" height="11" rx="1.5" fill="#f59e0b" />
          {/* Left Eye — Anchored perfectly to the top of the mid bar */}
          <circle cx="13" cy="18.5" r="2.2" fill="#0f172a" />
          <circle cx="13" cy="18.5" r="1.4" fill="#ffffff" />
          <circle cx="13" cy="18.5" r="0.6" fill="#0f172a" />
        </g>
        
        <g>
          <rect x="21.5" y="18.5" width="3" height="11" rx="1.5" fill="#f59e0b" />
          {/* Right Eye — Anchored perfectly to the top of the mid bar */}
          <circle cx="23" cy="18.5" r="2.2" fill="#0f172a" />
          <circle cx="23" cy="18.5" r="1.4" fill="#ffffff" />
          <circle cx="23" cy="18.5" r="0.6" fill="#0f172a" />
        </g>

        {/* Central main bar — Center locked exactly at x=18 */}
        <g>
            <rect x="16.5" y="14.5" width="3" height="15" rx="1.5" fill="#f59e0b" />
            {/* Nose — Base aligns seamlessly with the bottom of the central bar */}
            <circle cx="18" cy="27.5" r="2.2" fill="#0f172a" />
            <circle cx="18" cy="27.5" r="0.9" fill="#ffffff" />
        </g>
      </svg>
      
      {/* Refined Typography */}
      <span style={{ fontFamily: 'system-ui, sans-serif', fontSize: textSize, letterSpacing: '-0.03em', display: 'flex', alignItems: 'center' }}>
        <span style={{ fontWeight: 700, color: '#ffffff' }}>Lav</span>
        <span style={{ fontWeight: 500, color: '#f59e0b' }}>Bench</span>
      </span>
    </div>
  );
}