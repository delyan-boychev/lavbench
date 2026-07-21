import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import { useAuth } from '../../../AuthContext';
import { useApp } from '../../../context/AppContext';

const mockT = (key) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT, i18n: { language: 'en', changeLanguage: vi.fn() } }),
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}));

vi.mock('../../../hooks/useSSE', () => ({
  default: () => ({ data: null, error: null, connected: true, reconnect: vi.fn() }),
}));

vi.mock('../../../hooks/useQueueQuery', () => ({
  useQueueQuery: vi.fn(),
}));

vi.mock('../../../services/TaskService', () => ({
  default: {
    killSubmission: vi.fn(),
    clearQueue: vi.fn(),
  },
}));

vi.mock('../../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../../ui/Badge', () => ({
  default: ({ status }) => <span data-testid="badge">{status}</span>,
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, onClick, disabled, variant }) => (
    <button data-variant={variant} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
}));

import { useQueueQuery } from '../../../hooks/useQueueQuery';
import TaskService from '../../../services/TaskService';
import SubmissionQueue from '../SubmissionQueue';

const mockShowToast = vi.fn();
const mockConfirm = vi.fn(() => Promise.resolve(true));
const mockRefetch = vi.fn();

const sampleItems = [
  {
    id: 'sub-1',
    status: 'queued',
    user_alias: 'Alias-1',
    task_title: 'Task A',
    created_at: '2026-07-20T10:00:00Z',
  },
  {
    id: 'sub-2',
    status: 'running',
    user_alias: 'Alias-2',
    task_title: 'Task B',
    created_at: '2026-07-20T11:00:00Z',
  },
];

const defaultQueryResult = {
  data: { items: sampleItems, total: 2, page: 1, pages: 1 },
  isLoading: false,
  refetch: mockRefetch,
};

beforeEach(() => {
  vi.clearAllMocks();
  useQueueQuery.mockReturnValue(defaultQueryResult);
  useAuth.mockReturnValue({ currentUser: { role: 'admin' } });
  useApp.mockReturnValue({ showToast: mockShowToast, confirm: mockConfirm });
});

describe('SubmissionQueue — empty state', () => {
  it('shows empty state when no items', () => {
    useQueueQuery.mockReturnValue({
      data: { items: [], total: 0, page: 1, pages: 1 },
      isLoading: false,
      refetch: mockRefetch,
    });
    render(<SubmissionQueue />);

    expect(screen.getByText(/admin\.submission_queue\.queue_empty/i)).toBeInTheDocument();
    cleanup();
  });
});

describe('SubmissionQueue — table rendering', () => {
  it('renders items in table rows', () => {
    render(<SubmissionQueue />);

    expect(screen.getByText('Task A')).toBeInTheDocument();
    expect(screen.getByText('Task B')).toBeInTheDocument();
    expect(screen.getByText('Alias-1')).toBeInTheDocument();
    expect(screen.getByText('Alias-2')).toBeInTheDocument();
    cleanup();
  });

  it('shows status badges for each item', () => {
    render(<SubmissionQueue />);

    const badges = screen.getAllByTestId('badge');
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveTextContent('queued');
    expect(badges[1]).toHaveTextContent('running');
    cleanup();
  });

  it('renders kill button per item', () => {
    render(<SubmissionQueue />);

    const killBtns = screen.getAllByText(/admin\.submission_queue\.kill/i);
    expect(killBtns).toHaveLength(2);
    cleanup();
  });
});

describe('SubmissionQueue — kill action', () => {
  it('calls killSubmission and shows success toast', async () => {
    TaskService.killSubmission.mockResolvedValue({ ok: true, data: { message: 'Killed' } });

    render(<SubmissionQueue />);

    const killBtns = screen.getAllByText(/admin\.submission_queue\.kill/i);
    await act(async () => {
      fireEvent.click(killBtns[0]);
    });

    expect(mockConfirm).toHaveBeenCalled();
    expect(TaskService.killSubmission).toHaveBeenCalledWith('sub-1');
    expect(mockShowToast).toHaveBeenCalledWith(expect.any(String), 'emerald');
    cleanup();
  });

  it('shows error toast when kill fails', async () => {
    TaskService.killSubmission.mockResolvedValue({
      ok: false,
      data: { code: 'ERR_SUBMISSION_NOT_KILLABLE', error: 'Cannot kill' },
    });

    render(<SubmissionQueue />);

    const killBtns = screen.getAllByText(/admin\.submission_queue\.kill/i);
    await act(async () => {
      fireEvent.click(killBtns[0]);
    });

    expect(mockShowToast).toHaveBeenCalledWith(expect.any(String), 'rose');
    cleanup();
  });

  it('skips kill when confirm is cancelled', async () => {
    mockConfirm.mockResolvedValueOnce(false);

    render(<SubmissionQueue />);

    const killBtns = screen.getAllByText(/admin\.submission_queue\.kill/i);
    await act(async () => {
      fireEvent.click(killBtns[0]);
    });

    expect(TaskService.killSubmission).not.toHaveBeenCalled();
    cleanup();
  });
});

describe('SubmissionQueue — clear queue', () => {
  it('shows clear queue button for admin', () => {
    render(<SubmissionQueue />);

    expect(screen.getByText(/admin\.submission_queue\.clear_queue/i)).toBeInTheDocument();
    cleanup();
  });

  it('hides clear queue button for jury', () => {
    useAuth.mockReturnValue({ currentUser: { role: 'jury' } });

    render(<SubmissionQueue />);

    expect(screen.queryByText(/admin\.submission_queue\.clear_queue/i)).not.toBeInTheDocument();
    cleanup();
  });

  it('calls clearQueue and shows success toast', async () => {
    TaskService.clearQueue.mockResolvedValue({
      ok: true,
      data: { message: 'Cleared 2 submission(s)' },
    });

    render(<SubmissionQueue />);

    await act(async () => {
      fireEvent.click(screen.getByText(/admin\.submission_queue\.clear_queue/i));
    });

    expect(mockConfirm).toHaveBeenCalled();
    expect(TaskService.clearQueue).toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith(expect.stringContaining('Cleared'), 'emerald');
    cleanup();
  });
});

describe('SubmissionQueue — pagination', () => {
  it('renders pagination when items exceed perPage', () => {
    const manyItems = new Array(25).fill(null).map((_, i) => ({
      id: `sub-${i}`,
      status: 'queued',
      user_alias: `Alias-${i}`,
      task_title: `Task ${i}`,
      created_at: '2026-07-20T10:00:00Z',
    }));

    useQueueQuery.mockReturnValue({
      data: { items: manyItems, total: 25, page: 1, pages: 2 },
      isLoading: false,
      refetch: mockRefetch,
    });

    render(<SubmissionQueue />);

    expect(screen.getByText('2')).toBeInTheDocument();
    cleanup();
  });
});
