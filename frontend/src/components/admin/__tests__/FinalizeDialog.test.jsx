import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import FinalizeDialog from '../FinalizeDialog';

function renderDialog(props = {}) {
  const handlers = { onRevealChange: vi.fn(), onConfirm: vi.fn(), onClose: vi.fn() };
  render(
    <FinalizeDialog
      isOpen
      title="Finalize stage"
      revealLabel="Reveal the results now"
      revealId="reveal-stage"
      reveal={false}
      confirmLabel="Finalize"
      isPending={false}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe('FinalizeDialog', () => {
  it('shows the title and the reveal choice', () => {
    renderDialog();
    expect(screen.getByRole('dialog', { name: 'Finalize stage' })).toBeInTheDocument();
    const toggle = screen.getByLabelText('Reveal the results now');
    expect(toggle).toHaveAttribute('id', 'reveal-stage');
    expect(toggle).not.toBeChecked();
  });

  it('reports the reveal toggle', () => {
    const { onRevealChange } = renderDialog();
    fireEvent.click(screen.getByLabelText('Reveal the results now'));
    expect(onRevealChange).toHaveBeenCalledWith(true);
  });

  it('confirms with the confirm button', () => {
    const { onConfirm, onClose } = renderDialog({ reveal: true });
    expect(screen.getByLabelText('Reveal the results now')).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Finalize' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes with Cancel without confirming', () => {
    const { onConfirm, onClose } = renderDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('does not confirm twice while pending', () => {
    const { onConfirm } = renderDialog({ isPending: true });
    const button = screen.getByRole('button', { name: 'Finalize' });
    expect(button).toBeDisabled();
    fireEvent.submit(button.closest('form'));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('renders nothing while closed', () => {
    renderDialog({ isOpen: false });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
