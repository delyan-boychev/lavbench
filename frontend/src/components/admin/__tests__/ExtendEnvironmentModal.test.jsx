import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import ExtendEnvironmentModal from '../ExtendEnvironmentModal';

function renderModal(props = {}) {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <ExtendEnvironmentModal
      currentEnd="2027-05-01T17:00:00+03:00"
      timezone="Europe/Sofia"
      isPending={false}
      onClose={onClose}
      onSubmit={onSubmit}
      {...props}
    />,
  );
  return { onSubmit, onClose };
}

describe('ExtendEnvironmentModal', () => {
  it('starts from the current end in the competition time zone', () => {
    renderModal();
    expect(screen.getByRole('dialog')).toHaveTextContent('Move the end later');
    expect(screen.getByLabelText(/New end/)).toHaveValue('2027-05-01T17:00');
    expect(screen.getByText(/Time zone: Europe\/Sofia/)).toBeInTheDocument();
  });

  it('sends the new end and the trimmed reason', () => {
    const { onSubmit } = renderModal();
    fireEvent.change(screen.getByLabelText(/New end/), { target: { value: '2027-05-01T18:30' } });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: '  Network outage  ' } });
    fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
    expect(onSubmit).toHaveBeenCalledWith({
      end_time: '2027-05-01T18:30',
      reason: 'Network outage',
    });
  });

  it('does not send twice while a request is pending', () => {
    const { onSubmit } = renderModal({ isPending: true });
    fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('closes on Cancel', () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});
