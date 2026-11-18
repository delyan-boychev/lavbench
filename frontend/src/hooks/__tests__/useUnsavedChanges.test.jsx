import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hasUnsavedChanges, useDiscardGuard, useUnsavedChanges } from '../useUnsavedChanges';

const mockConfirm = vi.fn();
vi.mock('../../context/NotificationsContext', () => ({
  useNotifications: () => ({ showToast: vi.fn(), confirm: mockConfirm }),
}));

function fireBeforeUnload() {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event;
}

describe('useUnsavedChanges', () => {
  beforeEach(() => mockConfirm.mockReset());

  it('registers a dirty editor and forgets it when clean or unmounted', () => {
    const { rerender, unmount } = renderHook(({ dirty }) => useUnsavedChanges(dirty), {
      initialProps: { dirty: false },
    });
    expect(hasUnsavedChanges()).toBe(false);

    rerender({ dirty: true });
    expect(hasUnsavedChanges()).toBe(true);

    rerender({ dirty: false });
    expect(hasUnsavedChanges()).toBe(false);

    rerender({ dirty: true });
    unmount();
    expect(hasUnsavedChanges()).toBe(false);
  });

  it('counts each dirty editor separately', () => {
    const first = renderHook(() => useUnsavedChanges(true));
    const second = renderHook(() => useUnsavedChanges(true));
    first.unmount();
    expect(hasUnsavedChanges()).toBe(true);
    second.unmount();
    expect(hasUnsavedChanges()).toBe(false);
  });

  it('blocks unloading the page only while dirty', () => {
    const { rerender, unmount } = renderHook(({ dirty }) => useUnsavedChanges(dirty), {
      initialProps: { dirty: true },
    });
    expect(fireBeforeUnload().defaultPrevented).toBe(true);

    rerender({ dirty: false });
    expect(fireBeforeUnload().defaultPrevented).toBe(false);

    rerender({ dirty: true });
    unmount();
    expect(fireBeforeUnload().defaultPrevented).toBe(false);
  });
});

describe('useDiscardGuard', () => {
  beforeEach(() => mockConfirm.mockReset());

  it('resolves true without asking when nothing is unsaved', async () => {
    const { result } = renderHook(() => useDiscardGuard());
    await expect(result.current()).resolves.toBe(true);
    await expect(result.current(false)).resolves.toBe(true);
    expect(mockConfirm).not.toHaveBeenCalled();
  });

  it('asks before discarding and resolves with the answer', async () => {
    const { result } = renderHook(() => useDiscardGuard());

    mockConfirm.mockResolvedValueOnce(true);
    await expect(result.current(true)).resolves.toBe(true);
    expect(mockConfirm).toHaveBeenCalledWith({
      title: 'Discard unsaved changes?',
      message: 'You have changes that are not saved yet. Leave this form and lose them?',
      confirmText: 'Discard changes',
      cancelText: 'Keep editing',
    });

    mockConfirm.mockResolvedValueOnce(false);
    await expect(result.current(true)).resolves.toBe(false);

    mockConfirm.mockResolvedValueOnce(undefined);
    await expect(result.current(true)).resolves.toBe(false);
  });

  it('asks by default when a registered editor is dirty', async () => {
    const editor = renderHook(() => useUnsavedChanges(true));
    const { result } = renderHook(() => useDiscardGuard());

    mockConfirm.mockResolvedValueOnce(false);
    let answer;
    await act(async () => {
      answer = await result.current();
    });
    expect(answer).toBe(false);
    expect(mockConfirm).toHaveBeenCalledTimes(1);
    editor.unmount();
  });
});
