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

vi.mock('react-router-dom', () => ({
  useParams: vi.fn(),
  useNavigate: vi.fn(),
}));

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

import { useParams } from 'react-router-dom';
import { useApp } from '../../context/AppContext';

describe('Home Page', () => {
  const mockSetSelectedChallengeById = vi.fn();
  const mockSetSelectedTask = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useParams.mockReturnValue({ challengeId: undefined });
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
      /No competition selected or active/
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
    expect(screen.getByTestId('empty-state')).toHaveTextContent(
      /No task selected/
    );
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
    expect(mockSetSelectedChallengeById).toHaveBeenCalledWith(5);
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
