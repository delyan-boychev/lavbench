import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, act, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import TaskService from '../../services/TaskService';
import api from '../../services/ApiService';
import SubmissionsView from '../SubmissionsView';

vi.mock('../../AuthContext', () => {
  const React = require('react');
  return {
    useAuth: vi.fn(),
    AuthProvider: ({ children }) => React.createElement(React.Fragment, null, children),
  };
});

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../../services/TaskService', () => ({
  default: {
    selectFinal: vi.fn(),
    getSubmissions: vi.fn(),
    getSubmissionDetail: vi.fn(),
  },
}));

vi.mock('../../services/ApiService', () => ({
  default: {
    fetch: vi.fn(),
    get: vi.fn(),
    getBestSubmissions: vi.fn(),
  },
}));

describe('SubmissionsView Page', () => {
  const mockSetSelectedChallengeById = vi.fn();
  const mockSetSelectedTask = vi.fn();
  const mockConfirm = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(Date, 'now').mockImplementation(() => new Date('2026-06-13T12:00:00Z').getTime());
    global.URL.createObjectURL = vi.fn(() => 'blob:mock');
    global.URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();

    global.EventSource = class {
      close = vi.fn();
      onmessage = null;
      onerror = null;
    };

    // Default mocks for TaskService
    TaskService.getSubmissions.mockResolvedValue({
      ok: true,
      data: { items: [], total: 0, pages: 1 },
    });
    TaskService.getSubmissionDetail.mockResolvedValue({ ok: true, data: {} });
    api.getBestSubmissions.mockResolvedValue({ ok: true, data: { items: [] } });
    api.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
      blob: () => Promise.resolve(new Blob(['test'])),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // -------- Competitor tests --------
  describe('Competitor view', () => {
    beforeEach(() => {
      useAuth.mockReturnValue({
        currentUser: { id: 2, username: 'competitor1', role: 'competitor' },
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

      renderWithProviders(<SubmissionsView />);
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

      renderWithProviders(<SubmissionsView />);
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

      const mockSubmissions = [{ id: 100, status: 'queued', created_at: '2026-06-13T11:50:00Z' }];

      vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T11:55:00Z').getTime());

      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: mockSubmissions, total: mockSubmissions.length, pages: 1 },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(
          screen.getByText(/Waiting for running pre-deadline submissions/i),
        ).toBeInTheDocument();
      });
    });

    it('displays countdown timer showing remaining time to select final', async () => {
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
          id: 100,
          status: 'completed',
          created_at: '2026-06-13T11:50:00Z',
          executed_at: '2026-06-13T11:52:00Z',
        },
      ];
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: mockSubmissions, total: 1, pages: 1 },
      });

      vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T11:55:00Z').getTime());

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText(/Time remaining to select final: 11:00/i)).toBeInTheDocument();
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
          id: 100,
          status: 'completed',
          created_at: '2026-06-13T11:50:00Z',
          executed_at: '2026-06-13T11:52:00Z',
        },
      ];
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: mockSubmissions, total: 1, pages: 1 },
      });

      vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T12:06:00Z').getTime());

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
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

      renderWithProviders(<SubmissionsView />);

      const task2Btn = screen.getByText('Task 2');
      expect(task2Btn).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(task2Btn);
      });

      expect(mockSetSelectedTask).toHaveBeenCalledWith(mockTask2);
    });

    it('renders the selection timer and submissions from the REST list', async () => {
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

      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: mockSubmissions, total: 1, pages: 1 },
      });
      vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T11:55:00Z').getTime());

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText(/Time remaining to select final: 11:00/i)).toBeInTheDocument();
      });
      expect(await screen.findByText('#200')).toBeInTheDocument();
    });

    describe('live status (polling, no list stream)', () => {
      const task = { id: 10, title: 'Task 1' };
      let streams;

      beforeEach(() => {
        useApp.mockReturnValue({
          selectedChallenge: { id: 1, title: 'Challenge Alpha', stages: [], tasks: [task] },
          selectedTask: task,
          setSelectedChallengeById: mockSetSelectedChallengeById,
          setSelectedTask: mockSetSelectedTask,
          confirm: mockConfirm,
        });
        streams = [];
        global.EventSource = class {
          constructor(url) {
            this.url = url;
            this.close = vi.fn();
            streams.push(this);
          }
        };
      });

      it('opens no submissions list stream', async () => {
        TaskService.getSubmissions.mockResolvedValue({
          ok: true,
          data: {
            items: [{ id: 300, status: 'queued', created_at: '2026-06-13T11:50:00Z' }],
            total: 1,
            pages: 1,
          },
        });
        renderWithProviders(<SubmissionsView />);
        expect(await screen.findByText('#300')).toBeInTheDocument();
        expect(TaskService.getSubmissions).toHaveBeenCalledWith(10, 1, 10);
        expect(streams).toEqual([]);
      });

      it('refetches the selected submission when the list shows a newer status', async () => {
        const listed = { id: 301, status: 'completed', created_at: '2026-06-13T11:50:00Z' };
        TaskService.getSubmissions.mockResolvedValue({
          ok: true,
          data: { items: [listed], total: 1, pages: 1 },
        });
        TaskService.getSubmissionDetail
          .mockResolvedValueOnce({ ok: true, data: { ...listed, status: 'running' } })
          .mockResolvedValue({ ok: true, data: { ...listed, logs: 'stored final log' } });

        renderWithProviders(<SubmissionsView />);
        fireEvent.click(await screen.findByText('#301'));

        expect(await screen.findByText('stored final log')).toBeInTheDocument();
        expect(TaskService.getSubmissionDetail).toHaveBeenCalledTimes(2);
      });

      it('reloads the selected submission after its log stream reports a final status', async () => {
        const running = { id: 302, status: 'running', created_at: '2026-06-13T11:50:00Z' };
        const finished = { ...running, status: 'completed', logs: 'stored final log' };
        TaskService.getSubmissions.mockResolvedValue({
          ok: true,
          data: { items: [running], total: 1, pages: 1 },
        });
        TaskService.getSubmissionDetail.mockResolvedValue({ ok: true, data: running });

        renderWithProviders(<SubmissionsView />);
        fireEvent.click(await screen.findByText('#302'));

        await waitFor(() => {
          expect(streams.map((es) => es.url)).toContain('/api/submissions/302/logs/live');
        });
        const logStream = streams.find((es) => es.url === '/api/submissions/302/logs/live');

        TaskService.getSubmissions.mockResolvedValue({
          ok: true,
          data: { items: [finished], total: 1, pages: 1 },
        });
        TaskService.getSubmissionDetail.mockResolvedValue({ ok: true, data: finished });
        act(() => logStream.onmessage({ data: JSON.stringify({ status: 'completed' }) }));

        expect(await screen.findByText('stored final log')).toBeInTheDocument();
        expect(logStream.close).toHaveBeenCalled();
      });
    });

    it('selects final submission successfully', async () => {
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
          id: 100,
          status: 'completed',
          created_at: '2026-06-13T11:50:00Z',
          executed_at: '2026-06-13T11:52:00Z',
        },
      ];

      vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T11:55:00Z').getTime());

      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }),
      );
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: mockSubmissions, total: 1, pages: 1 },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText(/Time remaining to select final: 11:00/i)).toBeInTheDocument();
      });

      const submissionButton = await screen.findByText('#100');
      fireEvent.click(submissionButton);

      const toggleLabel = await screen.findByText(/Select as final submission/i);
      fireEvent.click(toggleLabel);

      await waitFor(() => {
        expect(TaskService.selectFinal).toHaveBeenCalledWith(100);
        expect(TaskService.getSubmissions).toHaveBeenCalledWith(10, 1, 10);
      });
    });

    it('handles final selection error', async () => {
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
          id: 100,
          status: 'completed',
          created_at: '2026-06-13T11:50:00Z',
          executed_at: '2026-06-13T11:52:00Z',
        },
      ];

      vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-13T11:55:00Z').getTime());

      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: mockSubmissions, total: 1, pages: 1 },
      });

      TaskService.selectFinal.mockResolvedValue({
        ok: false,
        data: { code: 'some_error', error: 'Something went wrong' },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText(/Time remaining to select final: 11:00/i)).toBeInTheDocument();
      });

      const submissionButton = await screen.findByText('#100');
      fireEvent.click(submissionButton);

      const toggleLabel = await screen.findByText(/Select as final submission/i);
      fireEvent.click(toggleLabel);

      await waitFor(() => {
        expect(mockConfirm).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Selection Error',
            message: expect.any(String),
          }),
        );
      });
    });

    it('renders best submission card correctly', async () => {
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

      const bestSubmission = {
        id: 99,
        status: 'completed',
        created_at: '2026-06-13T11:45:00Z',
        public_score: 0.9876,
        is_final_selection: true,
      };
      const otherSubmission = {
        id: 100,
        status: 'completed',
        created_at: '2026-06-13T11:50:00Z',
        public_score: 0.8765,
      };
      const mockSubmissions = [bestSubmission, otherSubmission];

      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: mockSubmissions, total: mockSubmissions.length, pages: 1 },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getAllByText('0.9876').length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText('Task 1')).toBeInTheDocument();
        expect(screen.getAllByText('Final').length).toBeGreaterThanOrEqual(1);
      });
    });

    it('handles empty submissions list', async () => {
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

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('No submissions found for this task.')).toBeInTheDocument();
      });
    });
  });

  // -------- Admin/Jury view --------
  describe('Admin/Jury view', () => {
    beforeEach(() => {
      useAuth.mockReturnValue({
        currentUser: { id: 1, username: 'admin', role: 'admin' },
      });
      // Default mock for api.fetch to always return success
      api.fetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
        blob: () => Promise.resolve(new Blob(['test'])),
      });
      global.EventSource = class MockEventSource {
        constructor() {
          this.close = vi.fn();
          this.onmessage = null;
          this.onerror = null;
        }
      };
    });

    const mockChallenge = {
      id: 1,
      title: 'Challenge Alpha',
      timezone: 'UTC',
      stages: [
        {
          id: 5,
          title: 'Stage 1',
          stage_number: 1,
          start_time: '2026-06-13T10:00:00Z',
          end_time: '2026-06-13T12:00:00Z',
          is_finalized: true,
          reveal_results: true,
        },
      ],
      tasks: [
        { id: 10, title: 'Task 1', stage_id: 5 },
        { id: 11, title: 'Task 2', stage_id: 5 },
      ],
    };

    const mockCompetitors = [
      {
        id: 101,
        username: 'comp1',
        alias_id: 'C1',
        name: 'John',
        surname: 'Doe',
        school: 'School A',
      },
      {
        id: 102,
        username: 'comp2',
        alias_id: 'C2',
        name: 'Jane',
        surname: 'Smith',
        school: 'School B',
      },
    ];

    it('does not load the competitor submissions list for admin or jury', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: mockChallenge.tasks[0],
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });
      renderWithProviders(<SubmissionsView />);
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
      expect(TaskService.getSubmissions).not.toHaveBeenCalled();
    });

    it('renders competitor search interface when no competitor selected', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });

      renderWithProviders(<SubmissionsView />);
      await act(async () => {});

      expect(screen.getByText('Select Competitor')).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/Search by alias, name, or school/i)).toBeInTheDocument();
    });

    it('searches competitors and displays results', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
        expect(screen.getByText('C2')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/Search by alias, name, or school/i);
      fireEvent.change(searchInput, { target: { value: 'John' } });

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=John'));
      });
    });

    it('debounces competitor search so rapid keystrokes fire a single request', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/Search by alias, name, or school/i);
      fireEvent.change(searchInput, { target: { value: 'Jo' } });
      fireEvent.change(searchInput, { target: { value: 'Joh' } });

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=Joh'));
      });

      const searchCalls = api.get.mock.calls.filter(([url]) => String(url).includes('search='));
      expect(searchCalls).toHaveLength(1);
    });

    it('selects a competitor and fetches their submissions', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });

      const subForTask1 = {
        id: 200,
        task_id: 10,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:30:00Z',
        public_score: 0.95,
        private_score: 0.92,
        is_final_selection: false,
      };
      const subForTask2 = {
        id: 201,
        task_id: 11,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:40:00Z',
        public_score: 0.88,
        private_score: 0.85,
        is_final_selection: true,
      };
      api.getBestSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [subForTask1, subForTask2] },
      });

      TaskService.getSubmissions
        .mockResolvedValueOnce({
          ok: true,
          data: { items: [subForTask1], total: 1, pages: 1 },
        })
        .mockResolvedValueOnce({
          ok: true,
          data: { items: [subForTask2], total: 1, pages: 1 },
        });

      api.fetch
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask2], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument(); // header
        expect(screen.getByText('Switch Competitor')).toBeInTheDocument();
        expect(screen.getByText('Stage 1')).toBeInTheDocument();
        expect(screen.getByText('Task 1')).toBeInTheDocument();
        expect(screen.getByText('Task 2')).toBeInTheDocument();
        expect(screen.getAllByText('Final').length).toBeGreaterThan(0);
      });
    });

    it('allows switching competitor', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [], total: 0, pages: 1 },
      });
      api.fetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('Switch Competitor')).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByText('Switch Competitor'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('Select Competitor')).toBeInTheDocument();
        expect(screen.queryByText('Switch Competitor')).not.toBeInTheDocument();
      });
    });

    it('displays submissions for a specific task when clicked', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      const subForTask1 = {
        id: 200,
        task_id: 10,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:30:00Z',
        public_score: 0.95,
        private_score: 0.92,
        is_final_selection: false,
      };
      const subForTask2 = {
        id: 201,
        task_id: 11,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:40:00Z',
        public_score: 0.88,
        private_score: 0.85,
        is_final_selection: true,
      };
      api.getBestSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [subForTask1, subForTask2] },
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });
      TaskService.getSubmissions
        .mockResolvedValueOnce({
          ok: true,
          data: { items: [subForTask1], total: 1, pages: 1 },
        })
        .mockResolvedValueOnce({
          ok: true,
          data: { items: [subForTask2], total: 1, pages: 1 },
        });
      api.fetch
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask2], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('Task 1')).toBeInTheDocument();
        expect(screen.getByText('Task 2')).toBeInTheDocument();
      });

      const task1Card = screen.getByText('Task 1').closest('button');
      fireEvent.click(task1Card);

      await waitFor(() => {
        const publicScoreLabels = screen.getAllByText(/Public Score/);
        expect(publicScoreLabels.length).toBeGreaterThan(1);
        expect(screen.getAllByText('0.9500').length).toBeGreaterThanOrEqual(1);
      });
    });

    it('handles download submission for admin', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      const subForTask1 = {
        id: 200,
        task_id: 10,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:30:00Z',
        public_score: 0.95,
        private_score: 0.92,
        is_final_selection: false,
      };
      api.getBestSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [subForTask1] },
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [subForTask1], total: 1, pages: 1 },
      });
      api.fetch
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [subForTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('Task 1')).toBeInTheDocument();
      });

      const task1Card = screen.getByText('Task 1').closest('button');
      fireEvent.click(task1Card);

      await waitFor(() => {
        const icons = screen.getAllByTitle('Download');
        expect(icons.length).toBeGreaterThanOrEqual(1);
      });

      await act(async () => {
        fireEvent.click(screen.getAllByTitle('Download')[0]);
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(api.fetch).toHaveBeenCalledWith(expect.stringContaining('/download'));
      });
    });

    it('handles admin submissions with is_final_selection badge', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      const finalSub = {
        id: 200,
        task_id: 10,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:30:00Z',
        public_score: 0.95,
        private_score: 0.92,
        is_final_selection: true,
      };
      api.getBestSubmissions.mockResolvedValue({ ok: true, data: { items: [finalSub] } });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [finalSub], total: 1, pages: 1 },
      });
      api.fetch
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [finalSub], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        })
        .mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ items: [finalSub], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getAllByText(/Final/).length).toBeGreaterThanOrEqual(1);
      });
    });

    it('handles pagination in competitor search', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      const manyCompetitors = Array.from({ length: 15 }, (_, i) => ({
        id: 200 + i,
        username: `comp${i}`,
        alias_id: `A${i}`,
        name: `Name${i}`,
        surname: `Surname${i}`,
        school: `School${i}`,
      }));

      api.get.mockResolvedValue({
        ok: true,
        data: { items: manyCompetitors.slice(0, 10), page: 1, pages: 2, total: 15 },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('A0')).toBeInTheDocument();
        expect(screen.getByText('A9')).toBeInTheDocument();
        expect(screen.queryByText('A10')).not.toBeInTheDocument();
      });

      const nextPageButton = screen.getByRole('button', { name: /next/i });
      fireEvent.click(nextPageButton);

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('page=2'));
      });
    });

    it('handles empty competitor search results', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: [], page: 1, pages: 1, total: 0 },
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('No competitors found')).toBeInTheDocument();
      });
    });

    it('shows loading state while searching competitors', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockImplementation(() => new Promise((resolve) => setTimeout(resolve, 100)));

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('Searching...')).toBeInTheDocument();
      });
    });

    it('requests and renders only the selected competitor submissions for every task', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      const subForTask1 = {
        id: 200,
        task_id: 10,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:30:00Z',
        public_score: 0.95,
        is_final_selection: false,
      };
      const subForTask2 = {
        id: 201,
        task_id: 11,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:40:00Z',
        public_score: 0.88,
        is_final_selection: true,
      };

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });
      api.getBestSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [subForTask1, subForTask2] },
      });
      api.fetch.mockImplementation((url) => {
        const itemsByUrl = {
          '/api/tasks/10/submissions?page=1&per_page=100&user_id=101': [subForTask1],
          '/api/tasks/11/submissions?page=1&per_page=100&user_id=101': [subForTask2],
          '/api/tasks/10/submissions?page=1&per_page=10&user_id=101': [subForTask1],
        };
        const items = itemsByUrl[url] || [];
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items, total: items.length, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('Task 1')).toBeInTheDocument();
        expect(screen.getByText('Task 2')).toBeInTheDocument();
        expect(screen.getAllByText('#200').length).toBeGreaterThan(0);
        expect(screen.getByText('#201')).toBeInTheDocument();
      });

      expect(api.getBestSubmissions).toHaveBeenCalledWith(1, 101);
      const taskSubmissionUrls = api.fetch.mock.calls
        .map(([url]) => url)
        .filter((url) => url.startsWith('/api/tasks/') && url.includes('/submissions?'));
      expect([...new Set(taskSubmissionUrls)]).toEqual([
        '/api/tasks/10/submissions?page=1&per_page=10&user_id=101',
      ]);
      expect(taskSubmissionUrls.every((url) => url.includes('user_id=101'))).toBe(true);
    });

    it('handles no submissions for a competitor', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [], total: 0, pages: 1 },
      });
      api.fetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('Stage 1')).toBeInTheDocument();
        expect(screen.getByText('Task 1')).toBeInTheDocument();
        expect(screen.getByText('Task 2')).toBeInTheDocument();
        expect(screen.getByText('No submissions found for this task.')).toBeInTheDocument();
      });
    });

    it('renders stage groups correctly when tasks have no stage_id', async () => {
      const challengeWithoutStages = {
        ...mockChallenge,
        stages: [],
        tasks: [
          { id: 10, title: 'Task 1', stage_id: null },
          { id: 11, title: 'Task 2', stage_id: null },
        ],
      };

      useApp.mockReturnValue({
        selectedChallenge: challengeWithoutStages,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      const subForTask1 = {
        id: 200,
        task_id: 10,
        user: { id: 101 },
        status: 'completed',
        created_at: '2026-06-13T11:30:00Z',
        public_score: 0.95,
        is_final_selection: false,
      };

      api.get.mockResolvedValue({
        ok: true,
        data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
      });
      TaskService.getSubmissions.mockResolvedValue({
        ok: true,
        data: { items: [subForTask1], total: 1, pages: 1 },
      });
      api.fetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ items: [subForTask1], total: 1, pages: 1 }),
      });

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => {
        expect(screen.getByText('C1')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByText('C1').closest('button'));
      });
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });

      await waitFor(() => {
        expect(screen.getByText('Challenge Alpha')).toBeInTheDocument();
        expect(screen.getByText('Task 1')).toBeInTheDocument();
      });
    });

    it('handles API errors during competitor search', async () => {
      useApp.mockReturnValue({
        selectedChallenge: mockChallenge,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      api.get.mockRejectedValue(new Error('Network error'));

      renderWithProviders(<SubmissionsView />);

      await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    });

    it('handles missing challenge during competitor search', async () => {
      useApp.mockReturnValue({
        selectedChallenge: null,
        selectedTask: null,
        setSelectedChallengeById: mockSetSelectedChallengeById,
        setSelectedTask: mockSetSelectedTask,
        confirm: mockConfirm,
      });

      renderWithProviders(<SubmissionsView />);
      expect(screen.getByText('No competition selected.')).toBeInTheDocument();
    });

    describe('Baseline submissions', () => {
      it('renders baseline section collapsed by default and does not fetch', async () => {
        api.get.mockResolvedValue({
          ok: true,
          data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
        });

        useApp.mockReturnValue({
          selectedChallenge: mockChallenge,
          selectedTask: null,
          setSelectedChallengeById: mockSetSelectedChallengeById,
          setSelectedTask: mockSetSelectedTask,
          confirm: mockConfirm,
        });

        renderWithProviders(<SubmissionsView />);

        await waitFor(() => {
          expect(screen.getByText('Baseline Solutions')).toBeInTheDocument();
        });
        expect(screen.queryByText('No baseline submissions available')).not.toBeInTheDocument();

        const baselineCalls = api.fetch.mock.calls.filter(([url]) => url.includes('baseline=true'));
        expect(baselineCalls.length).toBe(0);
      });

      it('shows no baselines message when expanded and no baselines exist', async () => {
        api.get.mockResolvedValue({
          ok: true,
          data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
        });

        useApp.mockReturnValue({
          selectedChallenge: mockChallenge,
          selectedTask: null,
          setSelectedChallengeById: mockSetSelectedChallengeById,
          setSelectedTask: mockSetSelectedTask,
          confirm: mockConfirm,
        });

        renderWithProviders(<SubmissionsView />);

        await waitFor(() => {
          expect(screen.getByText('Baseline Solutions')).toBeInTheDocument();
        });

        await act(async () => {
          fireEvent.click(screen.getByText('Baseline Solutions'));
        });

        await waitFor(() => {
          expect(screen.getByText('No baseline submissions available')).toBeInTheDocument();
        });
      });

      it('fetches and displays baseline cards when expanded', async () => {
        api.get.mockResolvedValue({
          ok: true,
          data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
        });

        const baselineTask1 = {
          id: 300,
          task_id: 10,
          status: 'completed',
          created_at: '2026-06-13T11:00:00Z',
          public_score: 0.99,
        };
        const baselineTask2 = {
          id: 301,
          task_id: 11,
          status: 'completed',
          created_at: '2026-06-13T11:05:00Z',
          public_score: 0.97,
        };

        api.fetch.mockReset();
        api.fetch.mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });
        api.fetch.mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [baselineTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });
        api.fetch.mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [baselineTask2], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

        useApp.mockReturnValue({
          selectedChallenge: mockChallenge,
          selectedTask: null,
          setSelectedChallengeById: mockSetSelectedChallengeById,
          setSelectedTask: mockSetSelectedTask,
          confirm: mockConfirm,
        });

        renderWithProviders(<SubmissionsView />);

        await waitFor(() => {
          expect(screen.getByText('Baseline Solutions')).toBeInTheDocument();
        });

        await act(async () => {
          fireEvent.click(screen.getByText('Baseline Solutions'));
        });

        await waitFor(() => {
          expect(screen.getByText('Task 1')).toBeInTheDocument();
          expect(screen.getByText('Task 2')).toBeInTheDocument();
          expect(screen.getByText('0.9900')).toBeInTheDocument();
          expect(screen.getByText('0.9700')).toBeInTheDocument();
        });
      });

      it('clicking a baseline card opens SubmissionViewer', async () => {
        api.get.mockResolvedValue({
          ok: true,
          data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
        });

        TaskService.getSubmissionDetail.mockResolvedValue({
          ok: true,
          data: {
            id: 300,
            task_id: 10,
            status: 'completed',
            public_score: 0.99,
            code_cells: ['print("hello")'],
            logs: 'test log',
          },
        });

        const baselineTask1 = {
          id: 300,
          task_id: 10,
          status: 'completed',
          created_at: '2026-06-13T11:00:00Z',
          public_score: 0.99,
        };

        api.fetch.mockReset();
        api.fetch.mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });
        api.fetch.mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [baselineTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });
        api.fetch.mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

        useApp.mockReturnValue({
          selectedChallenge: mockChallenge,
          selectedTask: null,
          setSelectedChallengeById: mockSetSelectedChallengeById,
          setSelectedTask: mockSetSelectedTask,
          confirm: mockConfirm,
        });

        renderWithProviders(<SubmissionsView />);

        await act(async () => {
          fireEvent.click(screen.getByText('Baseline Solutions'));
        });

        await waitFor(() => {
          expect(screen.getByText('Task 1')).toBeInTheDocument();
        });

        await act(async () => {
          fireEvent.click(screen.getByText('Task 1'));
        });

        await act(async () => {
          await new Promise((r) => setTimeout(r, 20));
        });

        await waitFor(() => {
          expect(TaskService.getSubmissionDetail).toHaveBeenCalledWith(300);
          expect(screen.getByText(/Submission #300/i)).toBeInTheDocument();
        });
      });

      it('hides SubmissionViewer when baseline section is collapsed', async () => {
        api.get.mockResolvedValue({
          ok: true,
          data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
        });

        TaskService.getSubmissionDetail.mockResolvedValue({
          ok: true,
          data: {
            id: 300,
            task_id: 10,
            status: 'completed',
            public_score: 0.99,
            code_cells: ['print("hello")'],
          },
        });

        const baselineTask1 = {
          id: 300,
          task_id: 10,
          status: 'completed',
          created_at: '2026-06-13T11:00:00Z',
          public_score: 0.99,
        };

        api.fetch.mockReset();
        api.fetch.mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });
        api.fetch.mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [baselineTask1], total: 1, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });
        api.fetch.mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

        useApp.mockReturnValue({
          selectedChallenge: mockChallenge,
          selectedTask: null,
          setSelectedChallengeById: mockSetSelectedChallengeById,
          setSelectedTask: mockSetSelectedTask,
          confirm: mockConfirm,
        });

        renderWithProviders(<SubmissionsView />);

        await act(async () => {
          fireEvent.click(screen.getByText('Baseline Solutions'));
        });
        await waitFor(() => {
          expect(screen.getByText('Task 1')).toBeInTheDocument();
        });

        await act(async () => {
          fireEvent.click(screen.getByText('Task 1'));
        });
        await waitFor(() => {
          expect(screen.getByText(/Submission #/i)).toBeInTheDocument();
        });

        await act(async () => {
          fireEvent.click(screen.getByText('Baseline Solutions'));
        });
        await waitFor(() => {
          expect(screen.queryByText(/Submission #/i)).not.toBeInTheDocument();
        });
      });

      it('collapses baseline section when a competitor is selected', async () => {
        api.get.mockResolvedValue({
          ok: true,
          data: { items: mockCompetitors, page: 1, pages: 1, total: 2 },
        });

        TaskService.getSubmissions.mockResolvedValue({
          ok: true,
          data: { items: [], total: 0, pages: 1 },
        });
        api.fetch.mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, pages: 1 }),
          blob: () => Promise.resolve(new Blob(['test'])),
        });

        useApp.mockReturnValue({
          selectedChallenge: mockChallenge,
          selectedTask: null,
          setSelectedChallengeById: mockSetSelectedChallengeById,
          setSelectedTask: mockSetSelectedTask,
          confirm: mockConfirm,
        });

        renderWithProviders(<SubmissionsView />);

        await act(async () => {
          fireEvent.click(screen.getByText('Baseline Solutions'));
        });
        await waitFor(() => {
          expect(screen.getByText('No baseline submissions available')).toBeInTheDocument();
        });

        await waitFor(() => {
          expect(screen.getByText('C1')).toBeInTheDocument();
        });
        await act(async () => {
          fireEvent.click(screen.getByText('C1').closest('button'));
        });
        await act(async () => {
          await new Promise((r) => setTimeout(r, 20));
        });

        await waitFor(() => {
          expect(screen.queryByText('Baseline Solutions')).not.toBeInTheDocument();
        });
      });
    });
  });
});
