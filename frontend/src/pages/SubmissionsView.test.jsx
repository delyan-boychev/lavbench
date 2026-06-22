import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import TaskService from '../services/TaskService';
import SubmissionsView from './SubmissionsView';

vi.mock('../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../services/TaskService', () => ({
  default: {
    getSubmissions: vi.fn(),
    getSubmissionDetail: vi.fn(),
  },
}));

vi.mock('../services/ApiService', () => ({
  default: {
    fetch: vi.fn(),
  },
}));

describe('SubmissionsView Page', () => {
  const mockSetSelectedChallengeById = vi.fn();
  const mockSetSelectedTask = vi.fn();
  const mockConfirm = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();

    useAuth.mockReturnValue({
      currentUser: { id: 2, username: 'student1', role: 'competitor' },
    });

    TaskService.getSubmissions.mockResolvedValue({
      ok: true,
      data: { items: [], total: 0, pages: 1 },
    });
  });

  it('renders empty state if no challenge is selected', () => {
    useApp.mockReturnValue({
      selectedChallenge: null,
      selectedTask: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    render(<SubmissionsView />);
    expect(screen.getByText('No competition selected.')).toBeInTheDocument();
  });

  it('renders empty state if no task is selected', () => {
    useApp.mockReturnValue({
      selectedChallenge: { id: 1, title: 'Challenge Alpha', tasks: [] },
      selectedTask: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    render(<SubmissionsView />);
    expect(screen.getByText('Please select a task to view submissions.')).toBeInTheDocument();
  });

  it('displays countdown timer for final selection correctly when running submissions exist', async () => {
    const mockStage = {
      id: 5,
      title: 'Stage 1',
      stage_number: 1,
      start_time: '2026-06-13T10:00:00Z',
      end_time: '2026-06-13T12:00:00Z',
    };

    const mockTask = {
      id: 10,
      title: 'Task 1',
      stage_id: 5,
    };

    useApp.mockReturnValue({
      selectedChallenge: {
        id: 1,
        title: 'Challenge Alpha',
        stages: [mockStage],
        tasks: [mockTask],
      },
      selectedTask: mockTask,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    const mockSubmissions = [
      {
        id: 100,
        status: 'queued',
        created_at: '2026-06-13T11:50:00Z',
      },
    ];
    global.EventSource = class {
      constructor() {
        this.close = vi.fn();
        setTimeout(() => {
          if (this.onmessage) this.onmessage({ data: JSON.stringify(mockSubmissions) });
        }, 10);
      }
    };

    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T11:55:00Z').getTime());

    render(<SubmissionsView />);

    await vi.waitFor(
      () => {
        expect(
          screen.getByText(/Waiting for running pre-deadline submissions/i),
        ).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it('displays countdown timer showing remaining time to select final', async () => {
    const mockStage = {
      id: 5,
      title: 'Stage 1',
      stage_number: 1,
      start_time: '2026-06-13T10:00:00Z',
      end_time: '2026-06-13T12:00:00Z',
    };

    const mockTask = {
      id: 10,
      title: 'Task 1',
      stage_id: 5,
    };

    useApp.mockReturnValue({
      selectedChallenge: {
        id: 1,
        title: 'Challenge Alpha',
        stages: [mockStage],
        tasks: [mockTask],
      },
      selectedTask: mockTask,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    global.EventSource = class {
      constructor() {
        this.close = vi.fn();
      }
    };

    const mockSubmissions = [
      {
        id: 100,
        status: 'completed',
        created_at: '2026-06-13T11:50:00Z',
        executed_at: '2026-06-13T11:52:00Z',
      },
    ];

    TaskService.getSubmissions.mockResolvedValue({
      ok: true,
      data: mockSubmissions,
    });

    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T12:02:00Z').getTime());

    render(<SubmissionsView />);

    await vi.waitFor(() => {
      expect(screen.getByText(/Time remaining to select final: 03:00/i)).toBeInTheDocument();
    });
  });

  it('displays Selection closed timer when time limit has expired', async () => {
    const mockStage = {
      id: 5,
      title: 'Stage 1',
      stage_number: 1,
      start_time: '2026-06-13T10:00:00Z',
      end_time: '2026-06-13T12:00:00Z',
    };

    const mockTask = {
      id: 10,
      title: 'Task 1',
      stage_id: 5,
    };

    useApp.mockReturnValue({
      selectedChallenge: {
        id: 1,
        title: 'Challenge Alpha',
        stages: [mockStage],
        tasks: [mockTask],
      },
      selectedTask: mockTask,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    const mockSubmissions = [
      {
        id: 100,
        status: 'completed',
        created_at: '2026-06-13T11:50:00Z',
        executed_at: '2026-06-13T11:52:00Z',
      },
    ];

    TaskService.getSubmissions.mockResolvedValue({
      ok: true,
      data: mockSubmissions,
    });

    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T12:06:00Z').getTime());

    render(<SubmissionsView />);

    await vi.waitFor(() => {
      expect(screen.getByText('Selection closed')).toBeInTheDocument();
    });
  });

  it('allows task switching and clears submission selection', async () => {
    const mockStage = {
      id: 5,
      title: 'Stage 1',
      stage_number: 1,
      start_time: '2026-06-13T10:00:00Z',
      end_time: '2026-06-13T12:00:00Z',
    };

    const mockTask1 = { id: 10, title: 'Task 1', stage_id: 5 };
    const mockTask2 = { id: 11, title: 'Task 2', stage_id: 5 };

    useApp.mockReturnValue({
      selectedChallenge: {
        id: 1,
        title: 'Challenge Alpha',
        stages: [mockStage],
        tasks: [mockTask1, mockTask2],
      },
      selectedTask: mockTask1,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    render(<SubmissionsView />);

    const task2Btn = screen.getByText('Task 2');
    expect(task2Btn).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(task2Btn);
    });

    expect(mockSetSelectedTask).toHaveBeenCalledWith(mockTask2);
  });

  it('renders timer and submissions after SSE onmessage loads data', async () => {
    const mockStage = {
      id: 5,
      title: 'Stage 1',
      stage_number: 1,
      start_time: '2026-06-13T10:00:00Z',
      end_time: '2026-06-13T12:00:00Z',
    };
    const mockTask = { id: 10, title: 'Task 1', stage_id: 5 };

    useApp.mockReturnValue({
      selectedChallenge: {
        id: 1,
        title: 'Challenge Alpha',
        stages: [mockStage],
        tasks: [mockTask],
      },
      selectedTask: mockTask,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    const mockSubmissions = [
      {
        id: 200,
        status: 'completed',
        created_at: '2026-06-13T11:50:00Z',
        executed_at: '2026-06-13T11:52:00Z',
      },
    ];
    global.EventSource = class {
      constructor() {
        this.close = vi.fn();
        setTimeout(() => {
          if (this.onmessage)
            this.onmessage({
              data: JSON.stringify({ items: mockSubmissions, total: 1, pages: 1 }),
            });
        }, 10);
      }
    };

    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T12:02:00Z').getTime());

    render(<SubmissionsView />);

    await vi.waitFor(
      () => {
        expect(screen.getByText(/Time remaining to select final: 03:00/i)).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it('falls back to api.fetch when SSE errors', async () => {
    const api = (await import('../services/ApiService')).default;
    api.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
    });

    const mockStage = {
      id: 5,
      title: 'Stage 1',
      stage_number: 1,
      start_time: '2026-06-13T10:00:00Z',
      end_time: '2026-06-13T12:00:00Z',
    };
    const mockTask = { id: 10, title: 'Task 1', stage_id: 5 };

    useApp.mockReturnValue({
      selectedChallenge: {
        id: 1,
        title: 'Challenge Alpha',
        stages: [mockStage],
        tasks: [mockTask],
      },
      selectedTask: mockTask,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      setSelectedTask: mockSetSelectedTask,
      confirm: mockConfirm,
    });

    global.EventSource = class {
      constructor() {
        this.close = vi.fn();
        setTimeout(() => {
          if (this.onerror) this.onerror(new Event('error'));
        }, 10);
      }
    };

    render(<SubmissionsView />);

    await vi.waitFor(
      () => {
        expect(api.fetch).toHaveBeenCalled();
      },
      { timeout: 5000 },
    );
  });
});
