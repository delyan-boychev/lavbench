import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../services/ApiService';
import { useChallengesQuery } from '../useChallengesQuery';

vi.mock('../../services/ApiService', () => ({
  default: {
    get: vi.fn(),
  },
}));

function createWrapper(queryClient) {
  return function Wrapper({ children }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe('useChallengesQuery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not fetch challenges without an authenticated user', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    renderHook(() => useChallengesQuery(undefined), {
      wrapper: createWrapper(queryClient),
    });

    expect(api.get).not.toHaveBeenCalled();
  });

  it('scopes challenge data to the authenticated user', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: { items: [{ id: 10, title: 'Challenge' }] },
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useChallengesQuery('user-1'), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.get).toHaveBeenCalledWith('/challenges');
    expect(queryClient.getQueryData(['challenges', 'user-1'])).toEqual([
      { id: 10, title: 'Challenge' },
    ]);
  });
});
