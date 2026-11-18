import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useUserEditor } from '../useUserEditor';
import { ApiRequestError } from '../../services/apiResult';

const mockShowToast = vi.fn();
const mockMutateAsync = vi.fn();
let mockIsPending = false;

vi.mock('../../context/NotificationsContext', () => ({
  useNotifications: () => ({ showToast: mockShowToast, confirm: vi.fn() }),
}));

vi.mock('../useUserMutations', () => ({
  useUpdateUser: () => ({ mutateAsync: mockMutateAsync, isPending: mockIsPending }),
}));

const competitor = {
  id: 42,
  username: 'ivan',
  email: 'ivan@example.com',
  name: 'Ivan',
  middle_name: null,
  surname: 'Petrov',
  birth_date: '2010-01-02',
  grade: '9',
  school: 'PMG',
  city: 'Sofia',
  challenge_id: 5,
  is_anonymous: true,
  role: 'competitor',
};

function openEditor(options) {
  const hook = renderHook(() => useUserEditor(options));
  act(() => hook.result.current.open(competitor));
  return hook;
}

describe('useUserEditor', () => {
  beforeEach(() => {
    mockShowToast.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending = false;
  });

  it('starts closed with an empty form', () => {
    const { result } = renderHook(() => useUserEditor());
    expect(result.current.user).toBeNull();
    expect(result.current.form.username).toBe('');
    expect(result.current.form.role).toBe('competitor');
    expect(result.current.dirty).toBe(false);
    expect(result.current.isLocked).toBe(false);
  });

  it('fills the form with string values when opened', () => {
    const { result } = openEditor();
    expect(result.current.user).toBe(competitor);
    expect(result.current.form).toMatchObject({
      username: 'ivan',
      email: 'ivan@example.com',
      password: '',
      middle_name: '',
      challenge_id: '5',
      is_anonymous: true,
      jury_challenges: [],
    });
    expect(result.current.dirty).toBe(false);
  });

  it('is dirty after an edit and clean again when the edit is undone', () => {
    const { result } = openEditor();
    act(() => result.current.update({ name: 'Ivo' }));
    expect(result.current.form.name).toBe('Ivo');
    expect(result.current.dirty).toBe(true);

    act(() => result.current.update({ name: 'Ivan' }));
    expect(result.current.dirty).toBe(false);
  });

  it('rejects an invalid email under its field without saving', async () => {
    const { result } = openEditor();
    act(() => result.current.update({ email: 'not-an-email' }));
    await act(() => result.current.submit());
    expect(result.current.errors.email).toBe('Please enter a valid email address');
    expect(mockMutateAsync).not.toHaveBeenCalled();

    // Editing the field clears its error
    act(() => result.current.update({ email: 'ivan@example.org' }));
    expect(result.current.errors.email).toBeUndefined();
  });

  it('saves with empty optional fields as null, toasts and closes', async () => {
    mockMutateAsync.mockResolvedValue({ ok: true, data: {} });
    const { result } = openEditor();
    act(() => result.current.update({ email: '', password: 'secret123' }));
    await act(() => result.current.submit());

    expect(mockMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 42,
        username: 'ivan',
        email: null,
        password: 'secret123',
        middle_name: null,
        challenge_id: '5',
        is_anonymous: true,
      }),
    );
    expect(mockShowToast).toHaveBeenCalledWith('Competitor updated successfully!');
    expect(result.current.user).toBeNull();
  });

  it('shows a server error that names a field under that field', async () => {
    mockMutateAsync.mockResolvedValue({
      ok: false,
      data: { code: 'ERR_USERNAME_TAKEN', error: 'Taken', field: 'username' },
    });
    const { result } = openEditor();
    await act(() => result.current.submit());

    expect(result.current.errors.username).toBe('User with this username already exists.');
    expect(mockShowToast).not.toHaveBeenCalled();
    expect(result.current.user).toBe(competitor);
  });

  it('toasts a server error that names no field', async () => {
    mockMutateAsync.mockResolvedValue({ ok: false, data: { error: 'Something broke' } });
    const { result } = openEditor();
    await act(() => result.current.submit());

    expect(mockShowToast).toHaveBeenCalledWith('Something broke', 'rose');
    expect(result.current.errors).toEqual({});
  });

  it('shows a thrown field error under the field and toasts any other failure', async () => {
    mockMutateAsync.mockRejectedValueOnce(
      new ApiRequestError({
        ok: false,
        status: 409,
        data: { code: 'ERR_USERNAME_TAKEN', error: 'Taken', field: 'username' },
      }),
    );
    const { result } = openEditor();
    await act(() => result.current.submit());
    expect(result.current.errors.username).toBe('User with this username already exists.');

    mockMutateAsync.mockRejectedValueOnce(new Error('offline'));
    await act(() => result.current.submit());
    expect(mockShowToast).toHaveBeenCalledWith('Network error updating competitor.', 'rose');
  });

  it('reports a locked competition through isLocked', () => {
    const isLocked = vi.fn((challengeId) => challengeId === '5');
    const { result } = openEditor({ isLocked });
    expect(result.current.isLocked).toBe(true);
    expect(isLocked).toHaveBeenCalledWith('5');

    act(() => result.current.update({ challenge_id: '6' }));
    expect(result.current.isLocked).toBe(false);
  });

  it('clears old errors when another user is opened and closes on demand', async () => {
    const { result } = openEditor();
    act(() => result.current.update({ email: 'bad' }));
    await act(() => result.current.submit());
    expect(result.current.errors.email).toBeDefined();

    act(() => result.current.open({ ...competitor, id: 43 }));
    expect(result.current.errors).toEqual({});

    act(() => result.current.close());
    expect(result.current.user).toBeNull();
    expect(result.current.dirty).toBe(false);
  });

  it('passes the pending state through as isSaving', () => {
    mockIsPending = true;
    const { result } = renderHook(() => useUserEditor());
    expect(result.current.isSaving).toBe(true);
  });
});
