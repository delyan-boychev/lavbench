import React from 'react';
import { useApp } from '../../context/AppContext';

export default function Logo({ size = 'md' }) {
  const { theme } = useApp();
  const svgRatio = 122 / 36;
  const heights = { sm: 24, md: 32, lg: 52, xl: 72 };
  const h = heights[size] || heights.md;
  const w = Math.round(h * svgRatio);
  const src = theme === 'dark' ? '/brand_logo_dark.svg' : '/brand_logo_light.svg';

  return (
    <div style={{ display: 'flex', alignItems: 'center', userSelect: 'none' }}>
      <img src={src} alt="LavBench" width={w} height={h} />
    </div>
  );
}
