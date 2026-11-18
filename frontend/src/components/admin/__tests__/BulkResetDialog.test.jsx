import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BulkResetDialog from '../BulkResetDialog';

const challenges = [
  { id: 1, title: 'Spring Cup' },
  { id: 2, title: 'Autumn Cup' },
];

function renderDialog() {
  const onChoose = vi.fn();
  const onClose = vi.fn();
  render(<BulkResetDialog challenges={challenges} onChoose={onChoose} onClose={onClose} />);
  return { onChoose, onClose };
}

describe('BulkResetDialog', () => {
  it('asks for a competition', () => {
    renderDialog();
    expect(screen.getByRole('dialog', { name: 'Bulk Reset Passwords' })).toBeInTheDocument();
    expect(
      screen.getByText(
        'Choose the competition whose competitors all get new passwords. You confirm on the next step.',
      ),
    ).toBeInTheDocument();
  });

  it('does not continue without a choice', () => {
    const { onChoose } = renderDialog();
    fireEvent.submit(screen.getByRole('button', { name: 'Continue' }).closest('form'));
    expect(onChoose).not.toHaveBeenCalled();
  });

  it('passes the chosen competition to onChoose', () => {
    const { onChoose, onClose } = renderDialog();
    fireEvent.click(screen.getByRole('combobox', { name: /Competition/ }));
    fireEvent.click(screen.getByRole('option', { name: 'Autumn Cup' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(onChoose).toHaveBeenCalledWith(challenges[1]);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes with Cancel', () => {
    const { onChoose, onClose } = renderDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onChoose).not.toHaveBeenCalled();
  });
});
