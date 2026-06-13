import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Badge from './Badge';

describe('Badge Component', () => {
  it('renders completed status correctly', () => {
    render(<Badge status="completed" />);
    const badge = screen.getByText('✓ Completed');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('text-emerald-400');
  });

  it('renders failed status correctly', () => {
    render(<Badge status="failed" />);
    const badge = screen.getByText('✗ Failed');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('text-rose-400');
  });

  it('renders running status correctly', () => {
    render(<Badge status="running" />);
    const badge = screen.getByText('⟳ Running');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('text-blue-400');
  });

  it('renders queued status correctly', () => {
    render(<Badge status="queued" />);
    const badge = screen.getByText('⏳ Queued');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('text-amber-400');
  });

  it('renders other known statuses correctly', () => {
    const { rerender } = render(<Badge status="building_env" />);
    expect(screen.getByText('⚙ Building Env')).toBeInTheDocument();

    rerender(<Badge status="running_inference" />);
    expect(screen.getByText('⚙ Inference')).toBeInTheDocument();

    rerender(<Badge status="evaluating" />);
    expect(screen.getByText('⚙ Evaluating')).toBeInTheDocument();

    rerender(<Badge status="active" />);
    expect(screen.getByText('● Active')).toBeInTheDocument();

    rerender(<Badge status="admin" />);
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });

  it('handles custom/unknown statuses gracefully', () => {
    render(<Badge status="unknown_status" />);
    const badge = screen.getByText('UNKNOWN_STATUS');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('text-slate-400');
  });

  it('handles null/undefined status gracefully', () => {
    const { container } = render(<Badge status={null} />);
    const badge = container.querySelector('span');
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toBe('');
  });
});
