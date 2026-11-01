import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import Home from '../Home';

vi.mock('../../components/challenge/ChallengeOverview', () => ({
  default: () => <div data-testid="challenge-overview">Challenge Overview</div>,
}));

vi.mock('../../components/challenge/TaskSidebar', () => ({
  default: () => <div data-testid="task-sidebar">Task Sidebar</div>,
}));

vi.mock('../../components/challenge/TaskDetail', () => ({
  default: () => <div data-testid="task-detail">Task Detail</div>,
}));

vi.mock('../../components/challenge/NotebookSubmit', () => ({
  default: () => <div data-testid="notebook-submit">Notebook Submit</div>,
}));

vi.mock('../../components/ui/EmptyState', () => ({
  default: ({ message }) => <div data-testid="empty-state">{message}</div>,
}));

vi.mock('react-router', () => ({
  useParams: vi.fn(),
  useNavigate: vi.fn(),
}));

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../../components/challenge/EnvironmentCard', () => ({
  default: () => <div data-testid="environment-card">Environment</div>,
}));

vi.mock('../../components/challenge/WorkspaceSubmit', () => ({
  default: () => <div data-testid="workspace-submit">Workspace Submit</div>,
}));

import { useParams } from 'react-router';
import { useApp } from '../../context/AppContext';
import { useAuth } from '../../AuthContext';

describe('Home Page', () => {
  const mockSetSelectedChallengeById = vi.fn();
  const mockSetSelectedTask = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useParams.mockReturnValue({ challengeId: undefined });
    useAuth.mockReturnValue({ currentUser: { role: 'admin' } });
  });

  const workspaceChallenge = {
    id: 'c1',
    stages: [{ id: 's1', compute_enabled: true }],
    tasks: [{ id: 't1', stage_id: 's1', workspace_submission_path: 'task1/submission.csv' }],
  };

  it('shows the environment card and workspace submit for competitors on workspace tasks', () => {
    useAuth.mockReturnValue({ currentUser: { role: 'competitor' } });
    useApp.mockReturnValue({
      selectedChallenge: workspaceChallenge,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: workspaceChallenge.tasks[0],
      setSelectedTask: mockSetSelectedTask,
    });
    render(<Home />);
    expect(screen.getByTestId('environment-card')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-submit')).toBeInTheDocument();
    expect(screen.queryByTestId('notebook-submit')).not.toBeInTheDocument();
  });

  it('keeps notebook upload when the stage has no published compute', () => {
    useAuth.mockReturnValue({ currentUser: { role: 'competitor' } });
    const challenge = { ...workspaceChallenge, stages: [{ id: 's1', compute_enabled: false }] };
    useApp.mockReturnValue({
      selectedChallenge: challenge,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: challenge.tasks[0],
      setSelectedTask: mockSetSelectedTask,
    });
    render(<Home />);
    expect(screen.getByTestId('notebook-submit')).toBeInTheDocument();
    expect(screen.queryByTestId('workspace-submit')).not.toBeInTheDocument();
  });

  it('hides the environment card and workspace submit from admins and jury', () => {
    useApp.mockReturnValue({
      selectedChallenge: workspaceChallenge,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: workspaceChallenge.tasks[0],
      setSelectedTask: mockSetSelectedTask,
    });
    render(<Home />);
    expect(screen.queryByTestId('environment-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('notebook-submit')).toBeInTheDocument();
  });

  it('renders EmptyState when no selectedChallenge and no URL param', () => {
    useApp.mockReturnValue({
      selectedChallenge: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: null,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state')).toHaveTextContent(
      /No competition selected or active/,
    );
  });

  it('renders EmptyState when selectedChallenge has no tasks', () => {
    useApp.mockReturnValue({
      selectedChallenge: { id: 1, title: 'Challenge', tasks: [] },
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: null,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(screen.getByTestId('challenge-overview')).toBeInTheDocument();
    expect(screen.getByTestId('task-sidebar')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state')).toHaveTextContent(/No task selected/);
  });

  it('renders ChallengeOverview + TaskSidebar + TaskDetail + NotebookSubmit when challenge with tasks is selected', () => {
    const mockTask = { id: 10, title: 'Task 1' };
    useApp.mockReturnValue({
      selectedChallenge: { id: 1, title: 'Challenge', tasks: [mockTask] },
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: mockTask,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(screen.getByTestId('challenge-overview')).toBeInTheDocument();
    expect(screen.getByTestId('task-sidebar')).toBeInTheDocument();
    expect(screen.getByTestId('task-detail')).toBeInTheDocument();
    expect(screen.getByTestId('notebook-submit')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-state')).not.toBeInTheDocument();
  });

  it('calls setSelectedChallengeById with URL param on mount', () => {
    useParams.mockReturnValue({ challengeId: '5' });
    useApp.mockReturnValue({
      selectedChallenge: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: null,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(mockSetSelectedChallengeById).toHaveBeenCalledWith('5');
  });

  it('uses selectedTask from AppContext', () => {
    const mockTask = { id: 10, title: 'Task 1' };
    useApp.mockReturnValue({
      selectedChallenge: { id: 1, title: 'Challenge', tasks: [mockTask] },
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: mockTask,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(screen.getByTestId('task-detail')).toBeInTheDocument();
    expect(screen.getByTestId('notebook-submit')).toBeInTheDocument();
  });

  it('auto-selects first task when challenge has tasks but selectedTask is null', () => {
    const mockTask = { id: 10, title: 'Task 1' };
    useApp.mockReturnValue({
      selectedChallenge: { id: 1, title: 'Challenge', tasks: [mockTask] },
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: null,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(mockSetSelectedTask).toHaveBeenCalledWith(mockTask);
  });

  it('does not auto-select task when selectedTask already exists', () => {
    const mockTask = { id: 10, title: 'Task 1' };
    useApp.mockReturnValue({
      selectedChallenge: {
        id: 1,
        title: 'Challenge',
        tasks: [mockTask, { id: 11, title: 'Task 2' }],
      },
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: mockTask,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(mockSetSelectedTask).not.toHaveBeenCalled();
  });

  it('does not call setSelectedChallengeById when no URL param', () => {
    useApp.mockReturnValue({
      selectedChallenge: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      selectedTask: null,
      setSelectedTask: mockSetSelectedTask,
    });

    render(<Home />);
    expect(mockSetSelectedChallengeById).not.toHaveBeenCalled();
  });
});
