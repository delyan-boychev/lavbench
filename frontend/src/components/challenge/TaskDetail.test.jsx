import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TaskDetail from './TaskDetail';
import TaskService from '../../services/TaskService';

// Mock TaskService
vi.mock('../../services/TaskService', () => ({
  default: {
    getDownloadUrl: vi.fn(),
  },
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
    require_submit_tag: true,
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
  });

  it('renders nothing when task is not provided', () => {
    const { container } = render(<TaskDetail task={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders task header, markdown description, and resource limits', () => {
    render(<TaskDetail task={taskMock} token="token-123" />);

    expect(screen.getByText('Task Epsilon')).toBeInTheDocument();
    expect(screen.getByTestId('markdown')).toHaveTextContent('Predict user engagement metrics.');

    // Resource limits formatting
    expect(screen.getByText('Resource Limits')).toBeInTheDocument();
    expect(screen.getByText('4096 MB')).toBeInTheDocument();
    expect(screen.getByText('120s')).toBeInTheDocument();
    expect(screen.getAllByText('Yes')).toHaveLength(3); // GPU, Require SUBMIT, and Ban Magic Commands
  });

  it('renders execution rules, banned libraries, and dataset properties', () => {
    render(<TaskDetail task={taskMock} token="token-123" />);

    expect(screen.getByText('Execution Rules')).toBeInTheDocument();
    // Banned libraries text
    expect(screen.getByText('sys,os')).toBeInTheDocument();

    // Dataset & Submissions metadata
    expect(screen.getByText('5 subs / 24h')).toBeInTheDocument();
    expect(screen.getByText('40% of Private Dataset')).toBeInTheDocument();
  });

  it('renders files, calculates megabytes, and calls authenticated download endpoint', async () => {
    const mockBlob = new Blob(['csv_data'], { type: 'text/csv' });
    const mockUrl = 'blob:http://localhost/mock-blob-url';

    // Mock window.URL.createObjectURL and revokeObjectURL
    window.URL.createObjectURL = vi.fn().mockReturnValue(mockUrl);
    window.URL.revokeObjectURL = vi.fn();

    // Mock global fetch to return blob
    global.fetch = vi.fn().mockResolvedValue({
      blob: async () => mockBlob,
    });

    TaskService.getDownloadUrl.mockReturnValue('/api/tasks/5/files/data_sample.csv');

    render(<TaskDetail task={taskMock} token="token-123" />);

    // File card check
    expect(screen.getByText('Task Files (1)')).toBeInTheDocument();
    expect(screen.getByText('data_sample.csv')).toBeInTheDocument();
    expect(screen.getByText('2.00 MB')).toBeInTheDocument(); // 2097152 bytes = 2 MB

    // Trigger download click
    const downloadBtn = screen.getByTitle('Download data_sample.csv');
    fireEvent.click(downloadBtn);

    expect(TaskService.getDownloadUrl).toHaveBeenCalledWith(5, 'data_sample.csv');
    expect(global.fetch).toHaveBeenCalledWith('/api/tasks/5/files/data_sample.csv', {
      headers: { 'Authorization': 'Bearer token-123', 'Content-Type': 'application/json' },
    });

    // Wait for the async download actions to finish
    await vi.waitFor(() => {
      expect(window.URL.createObjectURL).toHaveBeenCalledWith(mockBlob);
      expect(window.URL.revokeObjectURL).toHaveBeenCalledWith(mockUrl);
    });
  });

  it('renders jury custom evaluator notice when evaluator_script_path is present', () => {
    const taskWithCustomEval = {
      ...taskMock,
      evaluator_script_path: '/path/to/evaluator.py'
    };

    render(<TaskDetail task={taskWithCustomEval} token="token-123" />);

    expect(screen.getByText('Jury Custom Evaluator Active')).toBeInTheDocument();
    expect(screen.getByText(/This task uses a custom evaluator. Please ensure your submission defines the entry-point/)).toBeInTheDocument();
  });
});
