import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Logo from './Logo';

vi.mock('../../context/AppContext', () => ({
  useApp: () => ({ theme: 'dark' }),
}));

describe('Logo Component', () => {
  it('renders the LavBench wordmark', () => {
    render(<Logo />);
    expect(screen.getByText('Lav')).toBeInTheDocument();
    expect(screen.getByText('Bench')).toBeInTheDocument();
  });

  it('renders at small size', () => {
    render(<Logo size="sm" />);
    expect(screen.getByText('Lav')).toBeInTheDocument();
  });

  it('renders at large size', () => {
    render(<Logo size="lg" />);
    expect(screen.getByText('Lav')).toBeInTheDocument();
  });

  it('renders with dark theme styling', () => {
    render(<Logo />);
    expect(screen.getByText('Lav')).toBeInTheDocument();
  });
});
