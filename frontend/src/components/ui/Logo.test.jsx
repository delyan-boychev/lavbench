import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Logo from './Logo';

const mockUseApp = vi.hoisted(() => vi.fn());

vi.mock('../../context/AppContext', () => ({
  useApp: () => mockUseApp(),
}));

describe('Logo Component', () => {
  beforeEach(() => {
    mockUseApp.mockReset();
  });

  it('renders the brand logo image', () => {
    mockUseApp.mockReturnValue({ theme: 'dark' });
    render(<Logo />);
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('alt', 'LavBench');
  });

  it('uses dark logo in dark theme', () => {
    mockUseApp.mockReturnValue({ theme: 'dark' });
    render(<Logo />);
    const img = screen.getByRole('img');
    expect(img.getAttribute('src')).toMatch(/brand_logo_dark/);
  });

  it('uses light logo in light theme', () => {
    mockUseApp.mockReturnValue({ theme: 'light' });
    render(<Logo />);
    const img = screen.getByRole('img');
    expect(img.getAttribute('src')).toMatch(/brand_logo_light/);
  });

  it('renders at default md size', () => {
    mockUseApp.mockReturnValue({ theme: 'dark' });
    render(<Logo />);
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('height', '32');
  });

  it('renders at small size', () => {
    mockUseApp.mockReturnValue({ theme: 'dark' });
    render(<Logo size="sm" />);
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('height', '24');
  });

  it('renders at large size', () => {
    mockUseApp.mockReturnValue({ theme: 'dark' });
    render(<Logo size="lg" />);
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute("height", "52");
  });

  it('renders at xl size', () => {
    mockUseApp.mockReturnValue({ theme: 'dark' });
    render(<Logo size="xl" />);
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('height', '72');
  });
});
