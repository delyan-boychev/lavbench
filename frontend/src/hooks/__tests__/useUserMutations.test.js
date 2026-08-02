import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import api from '../../services/ApiService';
import {
  useRegisterUser,
  useUpdateUser,
  useDeleteUser,
  useResetPassword,
  useBulkResetPasswords,
} from '../useUserMutations';

vi.mock('../../services/ApiService', () => ({
  default: {
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useUserMutations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('useRegisterUser calls api.post', async () => {
    const { result } = renderHook(() => useRegisterUser(), { wrapper: createWrapper() });
    result.current.mutate({ username: 'newuser' });
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/admin/register-user', { username: 'newuser' }),
    );
  });

  it('useUpdateUser calls api.put', async () => {
    const { result } = renderHook(() => useUpdateUser(), { wrapper: createWrapper() });
    result.current.mutate({ id: 'u1', name: 'Updated' });
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/admin/users/u1', { name: 'Updated' }),
    );
  });

  it('useDeleteUser calls api.delete', async () => {
    const { result } = renderHook(() => useDeleteUser(), { wrapper: createWrapper() });
    result.current.mutate('u1');
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/admin/users/u1'));
  });

  it('useResetPassword calls api.post', async () => {
    const { result } = renderHook(() => useResetPassword(), { wrapper: createWrapper() });
    result.current.mutate('u1');
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/users/u1/reset-password'));
  });

  it('useBulkResetPasswords calls api.post', async () => {
    const { result } = renderHook(() => useBulkResetPasswords(), { wrapper: createWrapper() });
    result.current.mutate('c1');
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/admin/challenges/c1/reset-all-passwords'),
    );
  });
});
