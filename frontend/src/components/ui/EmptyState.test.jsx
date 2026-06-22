import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import EmptyState from './EmptyState';

describe('EmptyState Component', () => {
  it('renders message and custom children', () => {
    render(
      <EmptyState message="Nothing here">
        <span data-testid="child-el">Extra content</span>
      </EmptyState>,
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
    expect(screen.getByTestId('child-el')).toBeInTheDocument();
  });

  it('renders icon if provided', () => {
    render(<EmptyState icon={<span data-testid="icon-el">Icon</span>} message="No items found" />);
    expect(screen.getByTestId('icon-el')).toBeInTheDocument();
  });

  it('respects minHeight and surface props', () => {
    const { container } = render(
      <EmptyState message="Custom config" minHeight={350} surface={false} />,
    );
    const mainDiv = container.firstChild;
    expect(mainDiv).toHaveClass('empty-state');
    expect(mainDiv).not.toHaveClass('surface');
    expect(mainDiv).toHaveStyle({ minHeight: '350px' });
  });
});
