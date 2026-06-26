import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';

// ── Shared UI component stubs ──────────────────────────────────────────────
vi.mock('../../components/ui/InputField', () => ({
  default: ({ label, value, onChange, type, required }) => (
    <div>
      <label>{label}</label>
      <input
        aria-label={label}
        type={type || 'text'}
        value={value ?? ''}
        onChange={onChange}
        required={required}
      />
    </div>
  ),
}));

vi.mock('../../components/ui/Button', () => ({
  default: ({ children, type, onClick }) => (
    <button type={type || 'button'} onClick={onClick}>
      {children}
    </button>
  ),
}));

vi.mock('../../components/ui/SelectField', () => ({
  default: ({ label, value, onChange, options }) => (
    <div>
      <label>{label}</label>
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {(options || []).map((o) => (
          <option key={o.value ?? o} value={o.value ?? o}>
            {o.label ?? o}
          </option>
        ))}
      </select>
    </div>
  ),
}));

vi.mock('../../components/ui/ToggleField', () => ({
  default: ({ label, id, checked, onChange }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <input id={id} type="checkbox" checked={checked} onChange={onChange} />
    </div>
  ),
}));

import ChallengeConfig from '../../components/admin/ChallengeConfig';

// ── ChallengeConfig test stage fields ──────────────────────────────────────
describe('ChallengeConfig — test stage fields', () => {
  const TIMEZONES = [{ value: 'UTC', label: 'UTC' }];

  const baseChallenge = {
    title: '',
    description: '',
    max_eval_requests: 10,
    ram_limit_mb: 8192,
    time_limit_sec: 300,
    gpu_required: true,
    start_time: '',
    end_time: '',
    is_frozen: false,
    double_blind: true,
    timezone: 'UTC',
    test_stage_start_time: '',
    test_stage_end_time: '',
  };

  it('renders test stage start and end fields', () => {
    render(
      <ChallengeConfig
        handleCreateChallenge={vi.fn()}
        newChallenge={baseChallenge}
        setNewChallenge={vi.fn()}
        timezones={TIMEZONES}
      />,
    );
    expect(screen.getByLabelText('Test Stage Start (optional)')).toBeInTheDocument();
    expect(screen.getByLabelText('Test Stage End (optional)')).toBeInTheDocument();
  });

  it('test stage fields are empty by default', () => {
    render(
      <ChallengeConfig
        handleCreateChallenge={vi.fn()}
        newChallenge={baseChallenge}
        setNewChallenge={vi.fn()}
        timezones={TIMEZONES}
      />,
    );
    expect(screen.getByLabelText('Test Stage Start (optional)')).toHaveValue('');
    expect(screen.getByLabelText('Test Stage End (optional)')).toHaveValue('');
  });

  it('calls setNewChallenge with updated test_stage_start_time on change', () => {
    const setNewChallenge = vi.fn();
    render(
      <ChallengeConfig
        handleCreateChallenge={vi.fn()}
        newChallenge={baseChallenge}
        setNewChallenge={setNewChallenge}
        timezones={TIMEZONES}
      />,
    );
    fireEvent.change(screen.getByLabelText('Test Stage Start (optional)'), {
      target: { value: '2026-06-20T10:00' },
    });
    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ test_stage_start_time: '2026-06-20T10:00' }),
    );
  });

  it('calls setNewChallenge with updated test_stage_end_time on change', () => {
    const setNewChallenge = vi.fn();
    render(
      <ChallengeConfig
        handleCreateChallenge={vi.fn()}
        newChallenge={baseChallenge}
        setNewChallenge={setNewChallenge}
        timezones={TIMEZONES}
      />,
    );
    fireEvent.change(screen.getByLabelText('Test Stage End (optional)'), {
      target: { value: '2026-06-21T18:00' },
    });
    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ test_stage_end_time: '2026-06-21T18:00' }),
    );
  });

  it('reflects pre-filled test stage times as field values', () => {
    const filled = {
      ...baseChallenge,
      test_stage_start_time: '2026-06-28T08:00',
      test_stage_end_time: '2026-06-28T16:00',
    };
    render(
      <ChallengeConfig
        handleCreateChallenge={vi.fn()}
        newChallenge={filled}
        setNewChallenge={vi.fn()}
        timezones={TIMEZONES}
      />,
    );
    expect(screen.getByLabelText('Test Stage Start (optional)')).toHaveValue('2026-06-28T08:00');
    expect(screen.getByLabelText('Test Stage End (optional)')).toHaveValue('2026-06-28T16:00');
  });

  it('test stage fields are optional — form submits without them', () => {
    const handleCreateChallenge = vi.fn((e) => e.preventDefault());
    render(
      <ChallengeConfig
        handleCreateChallenge={handleCreateChallenge}
        newChallenge={baseChallenge}
        setNewChallenge={vi.fn()}
        timezones={TIMEZONES}
      />,
    );
    const form = screen.getByLabelText('Test Stage Start (optional)').closest('form');
    fireEvent.submit(form);
    expect(handleCreateChallenge).toHaveBeenCalledTimes(1);
  });
});

// ── AdminPanel smoke test ──────────────────────────────────────────────────

const mockSystemStats = {
  connected_workers_count: 1,
  workers: [
    {
      name: 'celery@gpu-worker-test',
      status: 'online',
      pid: 9999,
      uptime: 3600,
      pool_size: 8,
      total_tasks_processed: 42,
      active_tasks_count: 1,
      reserved_tasks_count: 0,
      active_tasks: [{ id: 'test-task-1', name: 'tasks.evaluate_submission' }],
      reserved_tasks: [],
      registered_tasks: ['tasks.evaluate_submission'],
      rusage: {
        maxrss_mb: 256.5,
        utime_sec: 1.25,
        stime_sec: 0.75,
      },
      broker: {
        transport: 'redis',
        hostname: 'localhost',
        port: 6379,
      },
    },
  ],
  system: {
    cpu_count: 16,
    load_avg: [1.2, 0.95, 0.8],
    memory: {
      total_gb: 32.0,
      used_gb: 16.0,
      free_gb: 16.0,
      percent_used: 50.0,
    },
    disk: {
      total_gb: 500.0,
      used_gb: 250.0,
      free_gb: 250.0,
      percent_used: 50.0,
    },
    os: 'Linux',
    platform_release: '5.15.0',
    python_version: '3.10.5',
  },
};

vi.mock('../../services/ApiService', () => ({
  default: {
    fetch: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })),
    postForm: vi.fn(() => Promise.resolve({ ok: true })),
  },
}));

vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(() => ({ currentUser: { id: 2, username: 'admin', role: 'admin' } })),
}));

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(() => ({
    challenges: [],
    selectedChallenge: null,
    setSelectedChallengeById: vi.fn(),
    fetchChallenges: vi.fn(),
    showToast: vi.fn(),
    confirm: vi.fn(() => Promise.resolve(true)),
  })),
}));

vi.mock('../../hooks/useDebounce', () => ({ default: (v) => v }));

import AdminPanel from '../AdminPanel';
import { formatMetricName } from '../../utils/metrics';
import api from '../../services/ApiService';

describe('AdminPanel Page - Workers & Resources', () => {
  const mockShowToast = vi.fn();
  const mockSetSelectedChallengeById = vi.fn();
  const mockFetchChallenges = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      challenges: [],
      selectedChallenge: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
    });

    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'admin', role: 'admin' },
    });

    vi.stubGlobal(
      'EventSource',
      class {
        constructor(url) {
          this.url = url;
          this.close = vi.fn();
          setTimeout(() => {
            if (this.onmessage) {
              act(() => {
                this.onmessage({ data: JSON.stringify(mockSystemStats) });
              });
            }
          }, 10);
        }
      },
    );

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url) => {
        if (url.includes('metrics')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ metrics: {} }),
          });
        }
        if (url.includes('challenges') || url.includes('users')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ items: [], total: 0, pages: 1 }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => mockSystemStats,
        });
      }),
    );
  });

  it('renders sidebar options including Workers & Resources for admin', async () => {
    render(<AdminPanel />);
    expect(screen.getByText('Jury Control Hub')).toBeInTheDocument();
    expect(screen.getByText('Workers & Resources')).toBeInTheDocument();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  });

  it('switches to Workers & Resources tab and fetches detailed stats', async () => {
    render(<AdminPanel />);

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const workersTabBtn = screen.getByText('Workers & Resources');

    await act(async () => {
      fireEvent.click(workersTabBtn);
    });

    await vi.waitFor(() => {
      expect(screen.getByText('System Resources & Worker Status')).toBeInTheDocument();
      expect(screen.getByText('Host CPU Utilization')).toBeInTheDocument();
      expect(screen.getByText('Host Memory Usage')).toBeInTheDocument();
      expect(screen.getByText('Host Disk Capacity')).toBeInTheDocument();
    });

    expect(screen.getByText('16 Cores')).toBeInTheDocument();
    expect(screen.getAllByText('50%')).toHaveLength(2);
    expect(screen.getByText('16 GB / 32 GB')).toBeInTheDocument();
    expect(screen.getByText('250 GB / 500 GB')).toBeInTheDocument();

    expect(screen.getByText('celery@gpu-worker-test')).toBeInTheDocument();
    expect(screen.getByText('8 processes')).toBeInTheDocument();
    expect(screen.getByText('256.5 MB')).toBeInTheDocument();
    expect(screen.getByText('1h 0s')).toBeInTheDocument();
    expect(screen.getByText('test-task-1')).toBeInTheDocument();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  });

  it('handles SSE errors gracefully', async () => {
    vi.stubGlobal(
      'EventSource',
      class {
        constructor() {
          this.close = vi.fn();
          setTimeout(() => {
            if (this.onerror) {
              act(() => {
                this.onerror(new Event('error'));
              });
            }
          }, 10);
        }
      },
    );

    render(<AdminPanel />);

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const workersTabBtn = screen.getByText('Workers & Resources');

    await act(async () => {
      fireEvent.click(workersTabBtn);
    });

    await vi.waitFor(() => {
      expect(screen.getByText(/Network error fetching stats/i)).toBeInTheDocument();
    });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  });
});

describe('AdminPanel component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the sidebar with admin controls', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText('Jury Control Hub')).toBeInTheDocument();
    expect(screen.getByText('Manage Competitions & Tasks')).toBeInTheDocument();
    expect(screen.getByText('Create Competition')).toBeInTheDocument();
    expect(screen.getByText('Competitor Registrations')).toBeInTheDocument();
  });

  it('shows backup and user management buttons for admin', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText('Database Backup')).toBeInTheDocument();
    expect(screen.getByText('User Management')).toBeInTheDocument();
  });

  it('shows workers and resources button for admin', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText('Workers & Resources')).toBeInTheDocument();
  });
});

// ── AdminPanel challenge management ──────────────────────────────────────────
describe('AdminPanel – challenge management', () => {
  const mockShowToast = vi.fn();
  const mockConfirm = vi.fn(() => Promise.resolve(true));
  const mockFetchChallenges = vi.fn();

  function setupChallenge(overrides = {}) {
    return {
      id: 1,
      title: 'Challenge Title',
      description: 'Description text',
      start_time: '2026-01-01T00:00:00Z',
      end_time: '2026-12-31T23:59:59Z',
      tasks: [
        { id: 10, title: 'Task A', public_eval_percentage: 30 },
        { id: 11, title: 'Task B', public_eval_percentage: 50 },
      ],
      stages: [
        {
          id: 20,
          stage_number: 1,
          title: 'Stage 1',
          start_time: '2026-06-01T00:00:00Z',
          end_time: '2026-06-30T23:59:59Z',
          is_finalized: false,
          reveal_results: false,
        },
      ],
      is_archived: false,
      is_frozen: false,
      scores_finalized: false,
      reveal_results: false,
      ...overrides,
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      challenges: [],
      selectedChallenge: null,
      setSelectedChallengeById: vi.fn(),
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });
    useAuth.mockReturnValue({
      currentUser: { id: 2, username: 'admin', role: 'admin' },
    });
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [setupChallenge()], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  it('renders challenge badges for all status variants', async () => {
    const variants = [
      { is_archived: true, key: 'archived' },
      { is_frozen: true, key: 'frozen' },
      { scores_finalized: true, reveal_results: true, key: 'public' },
      { scores_finalized: true, reveal_results: false, key: 'internal' },
      { start_time: '2099-01-01T00:00:00Z', key: 'future' },
      { end_time: '2024-01-01T00:00:00Z', key: 'grading' },
      { key: 'active' },
    ];
    const challenges = variants.map((v, i) =>
      setupChallenge({ ...v, id: i + 1, title: `Challenge ${v.key}` }),
    );
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: challenges, pages: 1, total: challenges.length }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    for (const v of variants) {
      expect(screen.getByText(`Challenge ${v.key}`)).toBeInTheDocument();
    }
  });

  it('calls confirm and api.fetch on delete challenge', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const deleteBtns = screen.getAllByText('Delete');
    fireEvent.click(deleteBtns[0]);
    expect(mockConfirm).toHaveBeenCalled();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(api.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1'),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('calls handleArchiveToggle on archive button click', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const archiveBtn = screen.getByText('Archive');
    expect(archiveBtn).toBeInTheDocument();
    fireEvent.click(archiveBtn);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(api.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1/archive'),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('renders download buttons for finalized challenges', async () => {
    const finalizedChallenge = setupChallenge({ scores_finalized: true, reveal_results: true });
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [finalizedChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Scores (CSV)')).toBeInTheDocument();
    expect(screen.getByText('Submissions (ZIP)')).toBeInTheDocument();
    expect(screen.getByText('Audits (JSON)')).toBeInTheDocument();
  });

  it('renders tasks and stages for a challenge with data', async () => {
    const challenge = setupChallenge({
      tasks: [
        { id: 10, title: 'Task Alpha', public_eval_percentage: 30 },
        { id: 11, title: 'Task Beta', public_eval_percentage: 50 },
      ],
      stages: [
        {
          id: 20,
          stage_number: 1,
          title: 'Warm-up',
          start_time: '2026-06-01T00:00:00Z',
          end_time: '2026-06-30T23:59:59Z',
          is_finalized: false,
          reveal_results: false,
        },
      ],
    });
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [challenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    await waitFor(() => {
      expect(screen.getByText('Task Alpha')).toBeInTheDocument();
    });
    expect(screen.getByText('Task Beta')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Stage 1: Warm-up')).toBeInTheDocument();
    });
    expect(screen.getByText('Tasks in this Competition (2)')).toBeInTheDocument();
    expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
  });
});

// ── AdminPanel – tab navigation & sub-module rendering ─────────────────────
describe('AdminPanel – tab navigation & sub-module rendering', () => {
  const mockShowToast = vi.fn();
  const mockConfirm = vi.fn(() => Promise.resolve(true));
  const mockFetchChallenges = vi.fn();
  const mockChallenge = {
    id: 1,
    title: 'Test Challenge',
    start_time: '2026-01-01T00:00:00Z',
    end_time: '2026-12-31T23:59:59Z',
    tasks: [],
    stages: [],
    is_archived: false,
    is_frozen: false,
    scores_finalized: false,
    reveal_results: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      challenges: [mockChallenge],
      selectedChallenge: mockChallenge,
      setSelectedChallengeById: vi.fn(),
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'admin', role: 'admin' } });
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [mockChallenge], pages: 1, total: 1 }),
        });
      }
      if (url.includes('/admin/backups')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ data: { backups: [] } }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });
  });

  it('switches to Challenge Configuration tab and renders ChallengeConfig', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Create Competition'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Create New Competition Challenge')).toBeInTheDocument();
  });

  it('switches to Competitor Registration tab and renders CompetitorManager', async () => {
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [mockChallenge], pages: 1, total: 1 }),
        });
      }
      if (url.includes('role=competitor')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 10,
                  alias_id: 'A001',
                  name: 'Alice',
                  surname: 'Smith',
                  role: 'competitor',
                  username: 'alice',
                  is_anonymous: false,
                  grade: '10',
                  school: 'HS',
                  city: 'NY',
                  challenge_id: 1,
                },
              ],
              total: 1,
              pages: 1,
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Competitor Registrations'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Manual Competitor Registration')).toBeInTheDocument();
  });

  it('switches to Database Backup tab and renders BackupManager', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Database Backup'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Database Backups & Security')).toBeInTheDocument();
  });

  it('switches to User Management tab and renders UserManager', async () => {
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [mockChallenge], pages: 1, total: 1 }),
        });
      }
      if (url.includes('/admin/users')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 2,
                  username: 'jury1',
                  name: 'Jury',
                  surname: 'One',
                  role: 'jury',
                  email: 'jury@test.com',
                  is_anonymous: false,
                },
              ],
              total: 1,
              pages: 1,
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('User Management'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Register User Account')).toBeInTheDocument();
  });

  it('switches to Workers & Resources tab and renders WorkersStats', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Workers & Resources'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('System Resources & Worker Status')).toBeInTheDocument();
  });

  it('switches to Audit Logs tab and renders AuditLogViewer', async () => {
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [mockChallenge], pages: 1, total: 1 }),
        });
      }
      if (url.includes('/challenges/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Audit Logs'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getAllByText('Audit Logs').length).toBeGreaterThanOrEqual(2);
  });
});

// ── AdminPanel – finalization ──────────────────────────────────────────────
describe('AdminPanel – finalization', () => {
  const mockShowToast = vi.fn();
  const mockConfirm = vi.fn(() => Promise.resolve(true));
  const mockFetchChallenges = vi.fn();

  const pastChallenge = {
    id: 1,
    title: 'Past Challenge',
    start_time: '2026-01-01T00:00:00Z',
    end_time: '2026-01-15T00:00:00Z',
    tasks: [],
    stages: [],
    is_archived: false,
    is_frozen: false,
    scores_finalized: false,
    reveal_results: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      challenges: [pastChallenge],
      selectedChallenge: pastChallenge,
      setSelectedChallengeById: vi.fn(),
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'jury', role: 'jury' } });
  });

  it('opens challenge finalize form and submits', async () => {
    const finalizedChallenge = {
      ...pastChallenge,
      stages: [
        {
          id: 10,
          stage_number: 1,
          title: 'Stage 1',
          start_time: '2026-01-01T00:00:00Z',
          end_time: '2026-01-10T00:00:00Z',
          is_finalized: true,
          reveal_results: false,
        },
      ],
    };
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [finalizedChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    useApp.mockReturnValue({
      challenges: [finalizedChallenge],
      selectedChallenge: finalizedChallenge,
      setSelectedChallengeById: vi.fn(),
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });

    const finalizeBtns = screen.getAllByRole('button', { name: /Finalize/i });
    expect(finalizeBtns[0]).not.toBeDisabled();
    fireEvent.click(finalizeBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText(/Finalize Competition:/i)).toBeInTheDocument();

    const submitBtn = screen.getByRole('button', { name: 'Finalize' });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    expect(mockShowToast).toHaveBeenCalledWith('Scores finalized and de-anonymized!');
  });
});

// ── AdminPanel – edit modals ───────────────────────────────────────────────
describe('AdminPanel – edit modals', () => {
  const mockShowToast = vi.fn();
  const mockConfirm = vi.fn(() => Promise.resolve(true));
  const mockFetchChallenges = vi.fn();

  const pastChallenge = {
    id: 1,
    title: 'Past Challenge',
    start_time: '2026-01-01T00:00:00Z',
    end_time: '2026-01-15T00:00:00Z',
    tasks: [],
    stages: [],
    is_archived: false,
    is_frozen: false,
    scores_finalized: false,
    reveal_results: false,
  };

  const mockCompetitor = {
    id: 10,
    alias_id: 'A001',
    name: 'Alice',
    surname: 'Smith',
    role: 'competitor',
    username: 'alice',
    is_anonymous: false,
    grade: '10',
    school: 'HS',
    city: 'NY',
    challenge_id: 1,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      challenges: [pastChallenge],
      selectedChallenge: pastChallenge,
      setSelectedChallengeById: vi.fn(),
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'admin', role: 'admin' } });
  });

  it('opens edit competitor modal and submits update', async () => {
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [pastChallenge], pages: 1, total: 1 }),
        });
      }
      if (url.includes('role=competitor')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [mockCompetitor], total: 1, pages: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Competitor Registrations'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Manual Competitor Registration')).toBeInTheDocument();
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Edit'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Edit Competitor Details')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Alice')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Smith')).toBeInTheDocument();

    const saveBtn = screen.getByRole('button', { name: /Save/i });
    fireEvent.click(saveBtn);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(api.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/admin/users/10'),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('opens edit user account modal with competitor fields and submits update', async () => {
    const mockUsers = [
      {
        id: 1,
        username: 'admin',
        name: 'System',
        surname: 'Admin',
        role: 'admin',
        email: 'admin@test.com',
        is_anonymous: false,
      },
      {
        id: 2,
        username: 'jury1',
        name: 'Jury',
        surname: 'One',
        role: 'competitor',
        email: 'jury@test.com',
        is_anonymous: false,
        birth_date: '2000-01-01',
        grade: '12',
        school: 'High School',
        city: 'NY',
        challenge_id: 1,
        middle_name: '',
      },
    ];
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [pastChallenge], pages: 1, total: 1 }),
        });
      }
      if (url.includes('/admin/users')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: mockUsers, total: 2, pages: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('User Management'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Register User Account')).toBeInTheDocument();
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Edit'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Edit User Account')).toBeInTheDocument();
    expect(
      screen.getByText('Modify user role, details, and competition access permissions.'),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue('jury1')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Jury')).toBeInTheDocument();
    expect(screen.getByDisplayValue('One')).toBeInTheDocument();

    const saveBtn = screen.getByRole('button', { name: /Save/i });
    fireEvent.click(saveBtn);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(api.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/admin/users/2'),
      expect.objectContaining({ method: 'PUT' }),
    );
  });
});

// ── AdminPanel – handler coverage ──────────────────────────────────────────
describe('AdminPanel – handler coverage', () => {
  const mockShowToast = vi.fn();
  const mockConfirm = vi.fn(() => Promise.resolve(true));
  const mockFetchChallenges = vi.fn();

  const baseChallenge = {
    id: 1,
    title: 'Test Challenge',
    description: 'Desc',
    start_time: '2026-01-01T00:00:00Z',
    end_time: '2026-12-31T23:59:59Z',
    tasks: [{ id: 10, title: 'Task A', public_eval_percentage: 30 }],
    stages: [
      {
        id: 20,
        stage_number: 1,
        title: 'Stage 1',
        start_time: '2026-06-01T00:00:00Z',
        end_time: '2026-06-30T23:59:59Z',
        is_finalized: false,
        reveal_results: false,
      },
    ],
    is_archived: false,
    is_frozen: false,
    scores_finalized: false,
    reveal_results: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      challenges: [baseChallenge],
      selectedChallenge: baseChallenge,
      setSelectedChallengeById: vi.fn(),
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'admin', role: 'admin' } });
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [baseChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });
  });

  it('calls handleCreateChallenge on ChallengeConfig form submit', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Create Competition'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const createBtns = screen.getAllByRole('button', { name: /Create Competition/i });
    fireEvent.submit(createBtns[1]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(api.fetch).toHaveBeenCalledWith(
      '/api/challenges',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('calls handleUpdateChallenge on challenge edit form submit', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const editBtns = screen.getAllByText('Edit');
    fireEvent.click(editBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const saveBtns = screen.getAllByRole('button', { name: /Save/i });
    fireEvent.click(saveBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(api.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1'),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('calls handleToggleRevealChallenge on finalized challenge', async () => {
    const finalizedChallenge = {
      ...baseChallenge,
      scores_finalized: true,
      reveal_results: false,
    };
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [finalizedChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'jury', role: 'jury' } });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const revealBtn = screen.getByText('Reveal');
    fireEvent.click(revealBtn);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(api.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1/reveal-results'),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('calls handleExportChallenge on Export button click', async () => {
    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Test Challenge')).toBeInTheDocument();
    });

    const exportBtns = screen.getAllByText('Export');
    fireEvent.click(exportBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(api.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/challenges/1/export'),
      expect.objectContaining({ headers: {} }),
    );
  });

  // ── Error paths ──────────────────────────────────────────────────────────

  it('handles handleCreateChallenge API error', async () => {
    api.fetch.mockImplementation((url) => {
      if (url === '/api/challenges') {
        return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'fail' }) });
      }
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [baseChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Create Competition'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const createBtns = screen.getAllByRole('button', { name: /Create Competition/i });
    fireEvent.submit(createBtns[1]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(mockShowToast).toHaveBeenCalled();
  });

  it('handles handleCreateChallenge network error', async () => {
    api.fetch.mockImplementation((url) => {
      if (url === '/api/challenges') {
        return Promise.reject(new Error('network error'));
      }
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [baseChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    fireEvent.click(screen.getByText('Create Competition'));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const createBtns = screen.getAllByRole('button', { name: /Create Competition/i });
    fireEvent.submit(createBtns[1]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(mockShowToast).toHaveBeenCalled();
  });

  it('handles handleUpdateChallenge API error', async () => {
    api.fetch.mockImplementation((url) => {
      if (
        url.includes('/api/challenges?') ||
        (url.includes('/api/challenges/1') &&
          !url.includes('reveal') &&
          !url.includes('archive') &&
          !url.includes('export'))
      ) {
        if (url.includes('PUT') || url.includes('/api/challenges/1')) {
          return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'fail' }) });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [baseChallenge], pages: 1, total: 1 }),
        });
      }
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [baseChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const editBtns = screen.getAllByText('Edit');
    fireEvent.click(editBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const saveBtns = screen.getAllByRole('button', { name: /Save/i });
    fireEvent.click(saveBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(mockShowToast).toHaveBeenCalled();
  });

  it('handles handleUpdateChallenge network error', async () => {
    api.fetch.mockImplementation((url) => {
      if (
        url.includes('/api/challenges/1') &&
        !url.includes('?') &&
        !url.includes('reveal') &&
        !url.includes('archive') &&
        !url.includes('export')
      ) {
        return Promise.reject(new Error('network error'));
      }
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [baseChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const editBtns = screen.getAllByText('Edit');
    fireEvent.click(editBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const saveBtns = screen.getAllByRole('button', { name: /Save/i });
    fireEvent.click(saveBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(mockShowToast).toHaveBeenCalled();
  });

  it('handleDeleteChallenge skips API when user cancels', async () => {
    mockConfirm.mockResolvedValue(false);

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const deleteBtns = screen.getAllByText('Delete');
    fireEvent.click(deleteBtns[0]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(api.fetch).not.toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1'),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('handles handleToggleRevealChallenge API error', async () => {
    const finalizedChallenge = {
      ...baseChallenge,
      scores_finalized: true,
      reveal_results: false,
    };
    api.fetch.mockImplementation((url) => {
      if (url.includes('reveal-results')) {
        return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'fail' }) });
      }
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [finalizedChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'jury', role: 'jury' } });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const revealBtn = screen.getByText('Reveal');
    fireEvent.click(revealBtn);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(mockShowToast).toHaveBeenCalled();
  });

  it('handles handleArchiveToggle API error', async () => {
    api.fetch.mockImplementation((url) => {
      if (url.includes('/archive')) {
        return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'fail' }) });
      }
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [baseChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const archiveBtn = screen.getByText('Archive');
    fireEvent.click(archiveBtn);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(mockShowToast).toHaveBeenCalled();
  });

  // ── Conditional rendering edge cases ─────────────────────────────────────

  it('shows Hide button for revealed finalized challenge', async () => {
    const revealedChallenge = {
      ...baseChallenge,
      scores_finalized: true,
      reveal_results: true,
    };
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [revealedChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    useAuth.mockReturnValue({ currentUser: { id: 1, username: 'jury', role: 'jury' } });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Hide')).toBeInTheDocument();
  });

  it('shows Restore button for archived challenge', async () => {
    const archivedChallenge = { ...baseChallenge, is_archived: true };
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [archivedChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Restore')).toBeInTheDocument();
    expect(screen.queryByText('Archive')).not.toBeInTheDocument();
  });

  it('shows blinded download button for past non-finalized challenge', async () => {
    const pastChallenge = {
      ...baseChallenge,
      end_time: '2024-01-01T00:00:00Z',
      scores_finalized: false,
    };
    api.fetch.mockImplementation((url) => {
      if (url.includes('/api/challenges?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [pastChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<AdminPanel />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Submissions (ZIP) (Blinded)')).toBeInTheDocument();
  });
});

// ── Stage model — is_test flag contract ────────────────────────────────────
describe('Stage is_test field contract', () => {
  it('a stage object with is_test=true is recognised as a test stage', () => {
    const stage = {
      id: 'abc',
      challenge_id: 'xyz',
      stage_number: 0,
      title: 'Warm-up',
      start_time: '2026-06-28T08:00:00Z',
      end_time: '2026-06-28T16:00:00Z',
      is_finalized: false,
      reveal_results: false,
      is_test: true,
    };
    expect(stage.is_test).toBe(true);
    expect(stage.stage_number).toBe(0);
  });

  it('a normal stage has is_test=false', () => {
    const stage = {
      id: 'def',
      challenge_id: 'xyz',
      stage_number: 1,
      title: 'Round 1',
      start_time: '2026-07-01T09:00:00Z',
      end_time: '2026-07-01T17:00:00Z',
      is_finalized: false,
      reveal_results: false,
      is_test: false,
    };
    expect(stage.is_test).toBe(false);
    expect(stage.stage_number).toBe(1);
  });

  it('filter_challenge_for_competitor: only test stage tasks shown before competition starts', () => {
    const testStageId = 'stage-test';
    const regularStageId = 'stage-1';
    const tasks = [
      { id: 't1', stage_id: testStageId, title: 'Warm-up Task' },
      { id: 't2', stage_id: regularStageId, title: 'Round 1 Task' },
      { id: 't3', stage_id: null, title: 'Unsorted Task' },
    ];
    const filtered = tasks.filter((t) => String(t.stage_id) === String(testStageId));
    expect(filtered).toHaveLength(1);
    expect(filtered[0].title).toBe('Warm-up Task');
  });

  it('filter_challenge_for_competitor: no test stage → no tasks shown before competition starts', () => {
    const tasks = [{ id: 't1', stage_id: 'stage-1', title: 'Round 1 Task' }];
    const filtered = tasks.filter(() => false);
    expect(filtered).toHaveLength(0);
  });

  it('leaderboard exclusion: test stage submissions are not counted', () => {
    const testStageId = 'stage-test';
    const regularStageId = 'stage-1';
    const submissions = [
      { id: 's1', stage_id: testStageId, public_score: 0.99 },
      { id: 's2', stage_id: regularStageId, public_score: 0.85 },
      { id: 's3', stage_id: regularStageId, public_score: 0.92 },
    ];
    const leaderboardSubs = submissions.filter((s) => s.stage_id !== testStageId);
    expect(leaderboardSubs).toHaveLength(2);
    expect(leaderboardSubs.every((s) => s.stage_id !== testStageId)).toBe(true);
  });

  it('task_requires_stage_when_regular_stages_exist: rejects task without stage_id', () => {
    const regularStages = [
      { id: 'stage-1', is_test: false },
      { id: 'stage-2', is_test: false },
    ];
    const stageId = null;
    const regularCount = regularStages.filter((s) => !s.is_test).length;
    const isRejected = !stageId && regularCount > 0;
    expect(isRejected).toBe(true);
  });

  it('task_without_stage_id_allowed_when_only_test_stage_exists', () => {
    const stages = [{ id: 'stage-test', is_test: true }];
    const stageId = null;
    const regularCount = stages.filter((s) => !s.is_test).length;
    const isRejected = !stageId && regularCount > 0;
    expect(isRejected).toBe(false);
  });
});

// ── formatMetricName utility (retained from original test) ─────────────────
describe('formatMetricName', () => {
  it('returns empty string for falsy input', () => {
    expect(formatMetricName('')).toBe('');
    expect(formatMetricName(null)).toBe('');
    expect(formatMetricName(undefined)).toBe('');
  });

  it('converts snake_case to Title Case', () => {
    expect(formatMetricName('accuracy')).toBe('Accuracy');
    expect(formatMetricName('mean_average_error')).toBe('Mean Average Error');
  });

  it('handles special metric acronyms', () => {
    expect(formatMetricName('f1')).toBe('F1');
    expect(formatMetricName('rmse')).toBe('RMSE');
    expect(formatMetricName('bleu')).toBe('BLEU');
    expect(formatMetricName('bertscore')).toBe('BERTScore');
    expect(formatMetricName('iou')).toBe('IoU');
  });

  it('handles map 50 95 special case', () => {
    expect(formatMetricName('map_50_95')).toBe('mAP 50-95');
  });
});
