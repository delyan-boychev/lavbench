import React, { useEffect } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { NotificationsProvider, useNotifications } from '../NotificationsContext';

/** @type {ReturnType<typeof useNotifications> | null} */
let actions = null;

function Capture({ onActions }) {
  const value = useNotifications();
  useEffect(() => onActions(value), [value, onActions]);
  return null;
}

const captureActions = (value) => {
  actions = value;
};

function renderProvider() {
  render(
    <NotificationsProvider>
      <Capture onActions={captureActions} />
    </NotificationsProvider>,
  );
}

describe('NotificationsContext confirm()', () => {
  it('resolves true when confirmed', async () => {
    renderProvider();
    let promise;
    act(() => {
      promise = actions.confirm({ title: 'Delete?', message: 'Sure?', confirmText: 'Yes' });
    });
    fireEvent.click(screen.getByText('Yes'));
    await expect(promise).resolves.toBe(true);
  });

  it('settles an overlapped confirm as cancelled and keeps the newest one live', async () => {
    renderProvider();
    let first;
    let second;
    act(() => {
      first = actions.confirm({ title: 'First', message: 'one', confirmText: 'OK first' });
    });
    act(() => {
      second = actions.confirm({ title: 'Second', message: 'two', confirmText: 'OK second' });
    });

    await expect(first).resolves.toBe(false);
    expect(screen.getByText('Second')).toBeInTheDocument();

    fireEvent.click(screen.getByText('OK second'));
    await expect(second).resolves.toBe(true);
  });

  it('settles an overlapped prompt with null', async () => {
    renderProvider();
    let first;
    act(() => {
      first = actions.confirm({ title: 'Name?', message: 'Enter', isPrompt: true });
    });
    act(() => {
      actions.confirm({ title: 'Other', message: 'x' });
    });
    await expect(first).resolves.toBeNull();
  });

  it('focuses the confirm button by default and Cancel when asked', async () => {
    renderProvider();
    act(() => {
      actions.confirm({ title: 'Save?', message: 'Sure?', confirmText: 'Save' });
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus());
    act(() => {
      actions.confirm({
        title: 'Publish?',
        message: 'This cannot be undone.',
        confirmText: 'Publish',
        cancelText: 'Cancel',
        focusCancel: true,
      });
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus());
  });

  it('renders a node message as given', () => {
    renderProvider();
    act(() => {
      actions.confirm({
        title: 'Publish?',
        message: (
          <ul>
            <li>Opens at noon</li>
          </ul>
        ),
      });
    });
    expect(screen.getByRole('listitem')).toHaveTextContent('Opens at noon');
  });
});
