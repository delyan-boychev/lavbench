import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Logo from './Logo';

// Mock the AppContext hook to prevent requiring AppProvider wrapper
vi.mock('../../context/AppContext', () => ({
  useApp: () => ({
    theme: 'dark',
  }),
}));

describe('Logo Component', () => {
  it('renders the branding text correctly', () => {
    render(<Logo />);
    expect(screen.getByText('NAI')).toBeInTheDocument();
    expect(screen.getByText('Platform')).toBeInTheDocument();
  });

  it('renders with default size (md)', () => {
    const { container } = render(<Logo />);
    const svgElement = container.querySelector('svg');
    expect(svgElement).toHaveAttribute('width', '28');
    expect(svgElement).toHaveAttribute('height', '28');

    const wordmark = screen.getByText('NAI');
    expect(wordmark.style.fontSize).toBe('1.1rem');
  });

  it('renders with small size (sm)', () => {
    const { container } = render(<Logo size="sm" />);
    const svgElement = container.querySelector('svg');
    expect(svgElement).toHaveAttribute('width', '22');
    expect(svgElement).toHaveAttribute('height', '22');

    const wordmark = screen.getByText('NAI');
    expect(wordmark.style.fontSize).toBe('0.95rem');
  });

  it('renders with large size (lg)', () => {
    const { container } = render(<Logo size="lg" />);
    const svgElement = container.querySelector('svg');
    expect(svgElement).toHaveAttribute('width', '28');
    expect(svgElement).toHaveAttribute('height', '28');

    const wordmark = screen.getByText('NAI');
    expect(wordmark.style.fontSize).toBe('1.4rem');
  });
});
