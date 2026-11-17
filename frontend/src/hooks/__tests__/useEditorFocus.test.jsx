import React, { useRef, useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useEditorFocus } from '../useEditorFocus';

function Editor({ focus = undefined, onClose }) {
  const ref = useRef(null);
  useEditorFocus(ref, focus === undefined ? undefined : { focus });
  return (
    <section ref={ref}>
      <h2>Edit user</h2>
      <input aria-label="Username" disabled />
      <input aria-label="Email" />
      <button type="button" onClick={onClose}>
        Close
      </button>
    </section>
  );
}

function List({ focus = undefined }) {
  const [open, setOpen] = useState(false);
  if (open) return <Editor focus={focus} onClose={() => setOpen(false)} />;
  return (
    <div>
      <button type="button" data-return-id="edit-1" onClick={() => setOpen(true)}>
        Edit one
      </button>
      <button type="button" data-return-id="edit-2" onClick={() => setOpen(true)}>
        Edit two
      </button>
    </div>
  );
}

describe('useEditorFocus', () => {
  it('focuses the first usable field on mount', () => {
    render(<Editor onClose={() => {}} />);
    expect(screen.getByLabelText('Email')).toHaveFocus();
  });

  it('focuses the heading in heading mode', () => {
    render(<Editor focus="heading" onClose={() => {}} />);
    const heading = screen.getByRole('heading', { name: 'Edit user' });
    expect(heading).toHaveFocus();
    expect(heading).toHaveAttribute('tabindex', '-1');
  });

  it('leaves the focus alone with focus null', () => {
    render(<Editor focus={null} onClose={() => {}} />);
    expect(screen.getByLabelText('Email')).not.toHaveFocus();
  });

  it('returns the focus to the trigger that opened it after closing', async () => {
    render(<List />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit two' }));
    expect(screen.getByLabelText('Email')).toHaveFocus();

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit two' })).toHaveFocus());
  });

  it('does not move the focus on close when no trigger opened it', async () => {
    const outside = document.createElement('button');
    document.body.appendChild(outside);
    // A click away from any trigger clears the remembered one
    fireEvent.click(outside);

    const { unmount } = render(<Editor onClose={() => {}} />);
    outside.focus();
    unmount();
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(outside).toHaveFocus();
    outside.remove();
  });
});
