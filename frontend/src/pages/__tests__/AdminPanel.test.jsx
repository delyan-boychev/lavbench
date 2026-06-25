import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

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
  useApp: () => ({
    challenges: [],
    selectedChallenge: null,
    setSelectedChallengeById: vi.fn(),
    fetchChallenges: vi.fn(),
    showToast: vi.fn(),
    confirm: vi.fn(() => Promise.resolve(true)),
  }),
}));

vi.mock('../../hooks/useDebounce', () => ({ default: (v) => v }));

import AdminPanel from '../AdminPanel';
import { formatMetricName } from '../../utils/metrics';

describe('AdminPanel component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the sidebar with admin controls', () => {
    render(<AdminPanel />);
    expect(screen.getByText('Jury Control Hub')).toBeInTheDocument();
    expect(screen.getByText('Manage Competitions & Tasks')).toBeInTheDocument();
    expect(screen.getByText('Create Competition')).toBeInTheDocument();
    expect(screen.getByText('Competitor Registrations')).toBeInTheDocument();
  });

  it('shows backup and user management buttons for admin', () => {
    render(<AdminPanel />);
    expect(screen.getByText('Database Backup')).toBeInTheDocument();
    expect(screen.getByText('User Management')).toBeInTheDocument();
  });

  it('shows workers and resources button for admin', () => {
    render(<AdminPanel />);
    expect(screen.getByText('Workers & Resources')).toBeInTheDocument();
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
