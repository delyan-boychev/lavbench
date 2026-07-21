import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import api from '../../services/ApiService';
import { useForceBackup, useDeleteBackup } from '../useBackupMutations';

vi.mock('../../services/ApiService', () => ({
  default: {
    post: vi.fn(),
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

describe('useBackupMutations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('useForceBackup calls api.post', async () => {
    const { result } = renderHook(() => useForceBackup(), { wrapper: createWrapper() });
    result.current.mutate();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/backups/force'));
  });

  it('useDeleteBackup calls api.delete with filename', async () => {
    const { result } = renderHook(() => useDeleteBackup(), { wrapper: createWrapper() });
    result.current.mutate('backup-2024.sql.gz');
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith('/admin/backups/backup-2024.sql.gz'),
    );
  });
});
