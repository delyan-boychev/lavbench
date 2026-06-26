import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Button from '../Button';

describe('Button Component', () => {
  it('renders children correctly', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('handles click events', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click me</Button>);
    fireEvent.click(screen.getByText('Click me'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('does not trigger onClick when disabled', () => {
    const handleClick = vi.fn();
    render(
      <Button onClick={handleClick} disabled={true}>
        Click me
      </Button>,
    );

    const button = screen.getByText('Click me');
    expect(button).toBeDisabled();

    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('applies variant classes correctly', () => {
    const { rerender } = render(<Button variant="primary">Primary</Button>);
    expect(screen.getByText('Primary')).toHaveClass('bg-indigo-600');

    rerender(<Button variant="danger">Danger</Button>);
    expect(screen.getByText('Danger')).toHaveClass('bg-rose-600');

    rerender(<Button variant="link">Link</Button>);
    expect(screen.getByText('Link')).toHaveClass('bg-transparent');
    expect(screen.getByText('Link')).toHaveClass('hover:underline');
  });

  it('passes title and custom className properties', () => {
    render(
      <Button title="Button Title" className="custom-class">
        Test
      </Button>,
    );
    const button = screen.getByText('Test');
    expect(button).toHaveAttribute('title', 'Button Title');
    expect(button).toHaveClass('custom-class');
  });

  it('respects type attribute', () => {
    render(<Button type="submit">Submit</Button>);
    expect(screen.getByText('Submit')).toHaveAttribute('type', 'submit');
  });
});
