import React, { useState } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Disclosure from '../Disclosure';

function Harness({ initial = false }) {
  const [open, setOpen] = useState(initial);
  return (
    <Disclosure label="More options" open={open} onToggle={() => setOpen(!open)} aside="aside">
      <p>Hidden detail</p>
    </Disclosure>
  );
}

describe('Disclosure', () => {
  it('keeps its content unrendered until opened', () => {
    render(<Harness />);
    const button = screen.getByRole('button', { name: 'More options' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Hidden detail')).not.toBeInTheDocument();
    expect(screen.getByText('aside')).toBeInTheDocument();

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    const detail = screen.getByText('Hidden detail');
    expect(button.getAttribute('aria-controls')).toBe(detail.parentElement.id);
  });

  it('shows the content when the caller opens it', () => {
    render(<Harness initial />);
    expect(screen.getByText('Hidden detail')).toBeVisible();
  });
});
