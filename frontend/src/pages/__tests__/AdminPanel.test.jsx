import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { formatMetricName } from '../../utils/metrics';

vi.mock('../../services/ApiService', () => ({
  default: {
    fetch: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })),
    postForm: vi.fn(() => Promise.resolve({ ok: true })),
  },
}));

vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(() => ({ currentUser: { id: 1, username: 'admin', role: 'admin' } })),
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

vi.mock('../../hooks/useDebounce', () => ({
  default: (v) => v,
}));

import AdminPanel from '../AdminPanel';

describe('AdminPanel component', () => {
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
