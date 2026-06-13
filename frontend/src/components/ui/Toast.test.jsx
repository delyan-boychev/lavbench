import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Toast from './Toast';

describe('Toast Component', () => {
  it('renders nothing when show is false', () => {
    const { container } = render(<Toast toast={{ show: false, message: 'Hello', type: 'success' }} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when toast is null/undefined', () => {
    const { container } = render(<Toast toast={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders message correctly when show is true', () => {
    render(<Toast toast={{ show: true, message: 'Operation successful', type: 'success' }} />);
    expect(screen.getByText('Operation successful')).toBeInTheDocument();
  });

  it('applies success theme styling correctly', () => {
    const { container } = render(<Toast toast={{ show: true, message: 'Success', type: 'success' }} />);
    const toastDiv = container.querySelector('.fixed');
    expect(toastDiv).toHaveClass('border-l-indigo-600');
    
    const indicator = container.querySelector('.h-2.w-2');
    expect(indicator).toHaveClass('bg-emerald-500');
  });

  it('applies error/danger theme styling correctly', () => {
    const { container } = render(<Toast toast={{ show: true, message: 'Failed', type: 'error' }} />);
    const toastDiv = container.querySelector('.fixed');
    expect(toastDiv).toHaveClass('border-l-rose-500');

    const indicator = container.querySelector('.h-2.w-2');
    expect(indicator).toHaveClass('bg-rose-500');
  });
});
