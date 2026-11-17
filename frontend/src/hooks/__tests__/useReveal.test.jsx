import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useReveal } from '../useReveal';

function Picker({ options = undefined, offscreen = false }) {
  const [ref, reveal] = useReveal(options);
  return (
    <div>
      <button type="button" onClick={reveal}>
        Choose
      </button>
      <section
        ref={(el) => {
          ref.current = el;
          // Content far below the button that chose it
          if (el && offscreen) {
            el.getBoundingClientRect = () => /** @type {DOMRect} */ ({ top: 3000, bottom: 3200 });
          }
        }}
      >
        <h2>Details</h2>
        <input aria-label="Name" />
      </section>
    </div>
  );
}

describe('useReveal', () => {
  beforeEach(() => vi.mocked(window.scrollTo).mockClear());
  afterEach(() => vi.unstubAllGlobals());

  it('does nothing until reveal is called', () => {
    render(<Picker options={{ focus: 'field' }} offscreen />);
    expect(window.scrollTo).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Name')).not.toHaveFocus();
  });

  it('scrolls to and focuses the first field after reveal', () => {
    render(<Picker options={{ focus: 'field' }} offscreen />);
    fireEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(window.scrollTo).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Name')).toHaveFocus();
  });

  it('reveals again on every call', () => {
    render(<Picker options={{ focus: 'heading' }} offscreen />);
    const button = screen.getByRole('button', { name: 'Choose' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(window.scrollTo).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('heading', { name: 'Details' })).toHaveFocus();
  });

  it('uses the latest options', () => {
    const { rerender } = render(<Picker options={{ focus: null }} />);
    rerender(<Picker options={{ focus: 'field' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(screen.getByLabelText('Name')).toHaveFocus();
  });

  it('skips a two-column layout with singleColumnOnly', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true })),
    );
    render(<Picker options={{ focus: 'field', singleColumnOnly: true }} offscreen />);
    fireEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(window.scrollTo).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Name')).not.toHaveFocus();
  });
});
