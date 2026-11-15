import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import TaskDetail from '../TaskDetail';
import TaskService from '../../../services/TaskService';
import { useAuth } from '../../../AuthContext';
import { saveBlob } from '../../../utils/download';

const mockShowToast = vi.fn();

vi.mock('../../../services/TaskService', () => ({
  default: {
    downloadFile: vi.fn(),
    getDownloadUrl: (taskId, filename) => `/api/tasks/${taskId}/download/${filename}`,
  },
}));
vi.mock('../../../AuthContext', () => ({
  useAuth: vi.fn(),
}));
vi.mock('../../../context/NotificationsContext', () => ({
  useNotifications: () => ({ showToast: mockShowToast }),
}));
vi.mock('../../../utils/download', () => ({
  saveBlob: vi.fn(),
}));

// Mock ReactMarkdown and remark-gfm to simplify formatting tests
vi.mock('react-markdown', () => ({
  default: ({ children }) => <div data-testid="markdown">{children}</div>,
}));
vi.mock('remark-gfm', () => ({
  default: () => {},
}));

describe('TaskDetail Component', () => {
  const taskMock = {
    id: 5,
    title: 'Task Epsilon',
    description: 'Predict user engagement metrics.',
    ram_limit_mb: 4096,
    time_limit_sec: 120,
    gpu_required: true,
    ban_magic_commands: true,
    banned_imports: 'sys,os',
    max_submissions_per_period: 5,
    submission_period_hours: 24,
    public_eval_percentage: 40,
    files: JSON.stringify([
      { filename: 'data_sample.csv', size_bytes: 2097152 }, // 2 MB
    ]),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
  });

  it('renders nothing when task is not provided', () => {
    const { container } = render(<TaskDetail task={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders task header, markdown description, and resource limits', () => {
    render(<TaskDetail task={taskMock} />);

    expect(screen.getByText('Task Epsilon')).toBeInTheDocument();
    expect(screen.getByTestId('markdown')).toHaveTextContent('Predict user engagement metrics.');

    // Resource limits formatting
    expect(screen.getByText('Resource Limits')).toBeInTheDocument();
    expect(screen.getByText('4096 MB')).toBeInTheDocument();
    expect(screen.getByText('120s')).toBeInTheDocument();
    expect(screen.getAllByText('Yes')).toHaveLength(2); // GPU and Ban Magic Commands
  });

  it('renders execution rules, banned libraries, and dataset properties', () => {
    render(<TaskDetail task={taskMock} />);

    expect(screen.getByText('Execution Rules')).toBeInTheDocument();
    // Banned libraries text
    expect(screen.getByText('sys,os')).toBeInTheDocument();

    // Dataset & Submissions metadata
    expect(screen.getByText('5 subs / 24h')).toBeInTheDocument();
    expect(screen.getByText('40% of Private Dataset')).toBeInTheDocument();
  });

  it('renders files and their size without fetching anything', () => {
    render(<TaskDetail task={taskMock} />);

    expect(screen.getByText('Task Files (1)')).toBeInTheDocument();
    expect(screen.getByText('data_sample.csv')).toBeInTheDocument();
    expect(screen.getByText('2.00 MB')).toBeInTheDocument(); // 2097152 bytes = 2 MB
    expect(TaskService.downloadFile).not.toHaveBeenCalled();
  });

  it('downloads a file through the API and saves the blob', async () => {
    const blob = new Blob(['a,b']);
    TaskService.downloadFile.mockResolvedValue({ ok: true, blob: async () => blob });

    render(<TaskDetail task={taskMock} />);
    fireEvent.click(screen.getByTitle('Download data_sample.csv'));

    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(blob, 'data_sample.csv'));
    expect(TaskService.downloadFile).toHaveBeenCalledWith(5, 'data_sample.csv');
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('shows the translated API error instead of saving an error response', async () => {
    useAuth.mockReturnValue({ currentUser: { id: 2, role: 'jury' } });
    TaskService.downloadFile.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ code: 'ERR_LABELS_NOT_AVAILABLE', error: 'server text' }),
    });
    const task = {
      ...taskMock,
      files: JSON.stringify([{ filename: 'labels.parquet', size_bytes: 10 }]),
    };

    render(<TaskDetail task={task} />);
    fireEvent.click(screen.getByTitle('Download labels.parquet'));

    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith(
        'Labels are not available yet for this challenge.',
        'rose',
      ),
    );
    expect(saveBlob).not.toHaveBeenCalled();
  });

  it('shows a generic error when the download request fails', async () => {
    TaskService.downloadFile.mockRejectedValue(new TypeError('Failed to fetch'));

    render(<TaskDetail task={taskMock} />);
    fireEvent.click(screen.getByTitle('Download data_sample.csv'));

    await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith('Download failed', 'rose'));
    expect(saveBlob).not.toHaveBeenCalled();
  });

  it('streams files over 50 MB through a plain link instead of fetching them', () => {
    const task = {
      ...taskMock,
      files: [{ filename: 'big_train.parquet', size_bytes: 300 * 1024 * 1024 }],
    };
    render(<TaskDetail task={task} />);

    const link = screen.getByRole('link', { name: /download/i });
    expect(link).toHaveAttribute('href', '/api/tasks/5/download/big_train.parquet');
    expect(link).toHaveAttribute('download', 'big_train.parquet');
    fireEvent.click(link);
    expect(TaskService.downloadFile).not.toHaveBeenCalled();
  });

  it('hides the solution from everyone and the labels from competitors', () => {
    const task = {
      ...taskMock,
      files: [
        { filename: 'train.csv', size_bytes: 10 },
        { filename: 'labels.parquet', size_bytes: 10 },
        { filename: 'solution.ipynb', size_bytes: 10, type: 'solution' },
      ],
    };

    const { unmount } = render(<TaskDetail task={task} />);
    expect(screen.getByText('Task Files (1)')).toBeInTheDocument();
    expect(screen.getByText('train.csv')).toBeInTheDocument();
    expect(screen.queryByText('labels.parquet')).not.toBeInTheDocument();
    expect(screen.queryByText('solution.ipynb')).not.toBeInTheDocument();
    unmount();

    useAuth.mockReturnValue({ currentUser: { id: 2, role: 'jury' } });
    render(<TaskDetail task={task} />);
    expect(screen.getByText('Task Files (2)')).toBeInTheDocument();
    expect(screen.getByText('labels.parquet')).toBeInTheDocument();
    expect(screen.queryByText('solution.ipynb')).not.toBeInTheDocument();
  });

  it('renders jury custom evaluator notice when evaluator_script_path is present', () => {
    const taskWithCustomEval = {
      ...taskMock,
      evaluator_script_path: '/path/to/evaluator.py',
    };

    render(<TaskDetail task={taskWithCustomEval} />);

    expect(screen.getByText('Jury Custom Evaluator Active')).toBeInTheDocument();
    expect(
      screen.getByText(
        /This task uses a custom evaluator. Please ensure your submission defines the entry-point/,
      ),
    ).toBeInTheDocument();
  });
});
