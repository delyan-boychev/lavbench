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

  it('says why finalising is not possible yet and blocks the confirm button', () => {
    const { onConfirm } = renderDialog({
      readiness: { ready: false, reason: 'runs_pending', available_at: null, pending_runs: 2 },
    });
    expect(
      screen.getByText(
        '2 submissions are still waiting to be scored. Finalizing is possible once they are scored.',
      ),
    ).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: 'Finalize' });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('names the stage deadline when a stage is not over', () => {
    renderDialog({
      isStage: true,
      readiness: { ready: false, reason: 'not_ended', available_at: '2026-06-13T12:03:00Z' },
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      /^Finalizing the stage is possible after its deadline and grace period, from /,
    );
  });

  it('lets a ready scope be finalised', () => {
    const { onConfirm } = renderDialog({ readiness: { ready: true } });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Finalize' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
