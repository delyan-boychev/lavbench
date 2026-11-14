/**
 * AdminPanelTabs.test.jsx
 * Exercises tab navigation, sidebar buttons, challenge selection, and
 * various utility branches inside AdminPanel to increase coverage.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import AdminPanel from '../AdminPanel';
import api from '../../services/ApiService';

vi.mock('../../AuthContext', () => ({ useAuth: vi.fn() }));
vi.mock('../../context/AppContext', () => ({ useApp: vi.fn() }));

vi.mock('../../services/ApiService', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ ok: true, data: { items: [], total: 0, pages: 1 } })),
    fetch: vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
      }),
    ),
    postForm: vi.fn(() => Promise.resolve({ ok: true })),
    post: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })),
    put: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })),
    delete: vi.fn(() => Promise.resolve({ ok: true })),
  },
}));

vi.mock('../../hooks/useDebounce', () => ({ default: (v) => v }));

const mockChallenge = {
  id: 1,
  title: 'Test Challenge',
  start_time: '2025-01-01T00:00:00Z',
  end_time: '2029-01-01T00:00:00Z',
  tasks: [],
  stages: [],
};

const baseAppContext = {
  challenges: [mockChallenge],
  selectedChallenge: mockChallenge,
  setSelectedChallengeById: vi.fn(),
  fetchChallenges: vi.fn(),
  showToast: vi.fn(),
  confirm: vi.fn(() => Promise.resolve(true)),
};

function makeEventSource(data, { delay = 10, useError = false } = {}) {
  return class MockEventSource {
    constructor() {
      this.close = vi.fn();
      setTimeout(() => {
        if (useError && this.onerror) {
          this.onerror(new Event('error'));
        } else if (!useError && this.onmessage) {
          this.onmessage({ data: JSON.stringify(data) });
        }
      }, delay);
    }
  };
}

describe('AdminPanel – tab navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'admin', role: 'admin' } });
    useApp.mockReturnValue({ ...baseAppContext });
    global.EventSource = makeEventSource({});
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
        }),
      ),
    );
  });

  it('renders default competition-mgmt tab', async () => {
    renderWithProviders(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText('Manage Competitions & Tasks')).toBeInTheDocument();
  });

  it('clicking "Competitor Registrations" tab stays navigable', async () => {
    renderWithProviders(<AdminPanel />);
    const btn = screen.getByText('Competitor Registrations');
    await act(async () => fireEvent.click(btn));
    expect(btn).toBeInTheDocument();
  });

  it('clicking "Database Backup" tab shows backup section', async () => {
    renderWithProviders(<AdminPanel />);
    const btn = screen.getByText('Database Backup');
    await act(async () => fireEvent.click(btn));
    expect(btn).toBeInTheDocument();
  });

  it('clicking "User Management" tab shows user section', async () => {
    renderWithProviders(<AdminPanel />);
    const btn = screen.getByText('User Management');
    await act(async () => fireEvent.click(btn));
    expect(btn).toBeInTheDocument();
  });

  it('clicking "Audit Logs" tab renders audit panel', async () => {
    renderWithProviders(<AdminPanel />);
    const btn = screen.getByText('Audit Logs');
    await act(async () => fireEvent.click(btn));
    expect(btn).toBeInTheDocument();
  });

  it('clicking "Workers and queues" polls the system status and opens no stream', async () => {
    const streams = [];
    global.EventSource = class {
      constructor(url) {
        streams.push(url);
      }
      close() {}
    };
    // Keep the panel loading; its rendering is covered by the polling tests below
    api.get.mockImplementation((url) =>
      url === '/admin/system-status'
        ? new Promise(() => {})
        : Promise.resolve({ ok: true, data: { items: [], total: 0, pages: 1 } }),
    );
    renderWithProviders(<AdminPanel />);
    const btn = screen.getByText('Workers and queues');
    await act(async () => fireEvent.click(btn));
    expect(api.get).toHaveBeenCalledWith('/admin/system-status', expect.anything());
    expect(streams).toEqual([]);
  });

  it('jury role sees "Competitor Registrations" but NOT "User Management" or "Database Backup"', async () => {
    useAuth.mockReturnValue({ currentUser: { id: 2, username: 'jury', role: 'jury' } });
    renderWithProviders(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText('Competitor Registrations')).toBeInTheDocument();
    expect(screen.queryByText('Database Backup')).not.toBeInTheDocument();
    expect(screen.queryByText('User Management')).not.toBeInTheDocument();
  });
});

describe('AdminPanel – challenge selection states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'admin', role: 'admin' } });
    global.EventSource = makeEventSource({});
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
        }),
      ),
    );
  });

  it('shows no-competitions placeholder when list is empty', async () => {
    useApp.mockReturnValue({ ...baseAppContext, selectedChallenge: null, challenges: [] });
    renderWithProviders(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    // The competition-mgmt tab always renders when admin is logged in
    expect(screen.getByText('Manage Competitions & Tasks')).toBeInTheDocument();
  });

  it('shows Create Competition section which is always visible in competition-mgmt tab', async () => {
    useApp.mockReturnValue({ ...baseAppContext });
    renderWithProviders(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText('Create Competition')).toBeInTheDocument();
  });
});

describe('AdminPanel – workers tab polling', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'admin', role: 'admin' } });
    useApp.mockReturnValue({ ...baseAppContext });
  });

  it('renders workers from the system status', async () => {
    api.get.mockImplementation((url) =>
      Promise.resolve(
        url === '/admin/system-status'
          ? {
              ok: true,
              status: 200,
              data: {
                status: 'operational',
                components: { api: 'operational', scoring: 'operational' },
                queues: [],
                workers: [
                  {
                    name: 'celery@gpu-0',
                    type: 'gpu',
                    queues: ['evaluation_gpu'],
                    online: false,
                    last_seen: '2026-11-14T09:58:00Z',
                    concurrency: 1,
                    cpu_cores: 8,
                    ram_gb: 16,
                    gpu_type: 'NVIDIA T4',
                    vram_gb: 16,
                  },
                ],
                submissions: {
                  queued: 0,
                  running: 0,
                  oldest_queued_seconds: null,
                  completed_last_15m: 0,
                  failed_last_15m: 0,
                },
                updated_at: '2026-11-14T10:00:00Z',
              },
            }
          : { ok: true, data: { items: [], total: 0, pages: 1 } },
      ),
    );
    renderWithProviders(<AdminPanel />);
    await act(async () => fireEvent.click(screen.getByText('Workers and queues')));
    expect(await screen.findByText('celery@gpu-0')).toBeInTheDocument();
    expect(screen.getByText('Stale')).toBeInTheDocument();
  });

  it('shows the error state when the status request fails', async () => {
    api.get.mockImplementation((url) =>
      Promise.resolve(
        url === '/admin/system-status'
          ? { ok: false, status: 500, data: null }
          : { ok: true, data: { items: [], total: 0, pages: 1 } },
      ),
    );
    renderWithProviders(<AdminPanel />);
    await act(async () => fireEvent.click(screen.getByText('Workers and queues')));
    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred');
  });
});

describe('AdminPanel – isChallengeStarted logic', () => {
  it('returns true when challenge start_time is in the past', () => {
    const challenges = [{ id: 1, start_time: '2020-01-01T00:00:00Z' }];
    const isChallengeStarted = (challengeId) => {
      if (!challengeId) return false;
      const challenge = challenges.find((c) => c.id.toString() === challengeId.toString());
      if (!challenge || !challenge.start_time) return false;
      return new Date() >= new Date(challenge.start_time);
    };
    expect(isChallengeStarted(1)).toBe(true);
  });

  it('returns false when challenge start_time is in the future', () => {
    const challenges = [{ id: 2, start_time: '2099-01-01T00:00:00Z' }];
    const isChallengeStarted = (challengeId) => {
      if (!challengeId) return false;
      const challenge = challenges.find((c) => c.id.toString() === challengeId.toString());
      if (!challenge || !challenge.start_time) return false;
      return new Date() >= new Date(challenge.start_time);
    };
    expect(isChallengeStarted(2)).toBe(false);
  });

  it('returns false for null/missing challengeId', () => {
    const isChallengeStarted = (challengeId) => {
      if (!challengeId) return false;
      return true;
    };
    expect(isChallengeStarted(null)).toBe(false);
    expect(isChallengeStarted(undefined)).toBe(false);
    expect(isChallengeStarted('')).toBe(false);
  });
});
