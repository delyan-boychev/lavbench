import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Notice from '../Notice';

describe('Notice', () => {
  it('renders its content with the info tone by default', () => {
    render(<Notice>Private scores stay hidden.</Notice>);
    const box = screen.getByText('Private scores stay hidden.');
    expect(box.className).toContain('text-slate-300');
  });

  it('applies the requested tone, role and extra classes', () => {
    render(
      <Notice tone="error" role="alert" className="mb-6">
        Invalid credentials
      </Notice>,
    );
    const box = screen.getByRole('alert');
    expect(box).toHaveTextContent('Invalid credentials');
    expect(box.className).toContain('text-rose-400');
    expect(box.className).toContain('mb-6');
  });
});
