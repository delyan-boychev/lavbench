import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import ChallengeService from '../../services/ChallengeService';
import TaskService from '../../services/TaskService';
import NotebookSubmit from './NotebookSubmit';

// Mock contexts
vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

// Mock services
vi.mock('../../services/ChallengeService', () => ({
  default: {
    parseNotebook: vi.fn(),
  },
}));

vi.mock('../../services/TaskService', () => ({
  default: {
    submit: vi.fn(),
  },
}));

describe('NotebookSubmit Component', () => {
  const mockShowToast = vi.fn();
  const task = { id: 1, title: 'Task A' };
  const challenge = { id: 10, is_active: true, is_archived: false, max_eval_requests: 5 };

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      showToast: mockShowToast,
    });
  });

  it('renders judge/admin session banner when role is not competitor', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'admin' },
    });

    render(<NotebookSubmit task={task} challenge={challenge} />);
    expect(screen.getByText('Judge / Admin Session Active')).toBeInTheDocument();
    expect(screen.queryByText('Submit Solution')).not.toBeInTheDocument();
  });

  it('renders competition closed banner if challenge is inactive', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    const inactiveChallenge = { ...challenge, is_active: false };
    render(<NotebookSubmit task={task} challenge={inactiveChallenge} />);
    expect(screen.getByText('Competition Closed')).toBeInTheDocument();
  });

  it('renders competition closed banner if challenge is archived', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    const archivedChallenge = { ...challenge, is_archived: true };
    render(<NotebookSubmit task={task} challenge={archivedChallenge} />);
    expect(screen.getByText('Competition Closed')).toBeInTheDocument();
  });

  it('renders upload panel normally for active competitor', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    render(<NotebookSubmit task={task} challenge={challenge} />);
    expect(screen.getByText('Submit Solution')).toBeInTheDocument();
    expect(screen.getByText('Upload Jupyter Notebook (.ipynb)')).toBeInTheDocument();
  });

  it('validates file extension upon upload selection', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    render(<NotebookSubmit task={task} challenge={challenge} />);

    // Query file input element
    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);

    // Mock an invalid text file
    const invalidFile = new File(['print("hello")'], 'solution.py', { type: 'text/x-python' });
    fireEvent.change(fileInput, { target: { files: [invalidFile] } });

    expect(mockShowToast).toHaveBeenCalledWith('Only .ipynb files are supported.', 'error');
    expect(ChallengeService.parseNotebook).not.toHaveBeenCalled();
  });

  it('calls parseNotebook on valid .ipynb selection and updates cell list', async () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    const cellsMock = [
      { id: 0, type: 'markdown', source: '## Notebook Description' },
      { id: 1, type: 'code', source: 'import numpy as np' },
      { id: 2, type: 'code', source: 'def predict(x):\n  return 1' },
    ];

    ChallengeService.parseNotebook.mockResolvedValue({
      ok: true,
      data: {
        filename: 'my_solution.ipynb',
        cells: cellsMock,
      },
    });

    render(<NotebookSubmit task={task} challenge={challenge} />);

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['{}'], 'my_solution.ipynb', { type: 'application/json' });

    fireEvent.change(fileInput, { target: { files: [validFile] } });

    expect(ChallengeService.parseNotebook).toHaveBeenCalledWith(10, validFile);

    // Give state transitions time to process
    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Parsed 3 cells from "my_solution.ipynb".');
      expect(screen.getByText('Select Cells (0/2 code cells)')).toBeInTheDocument();
      expect(screen.getByText(/Cell \[1\]/)).toBeInTheDocument();
      expect(screen.getByText(/Cell \[2\]/)).toBeInTheDocument();
    });
  });

  it('handles parseNotebook server error response gracefully', async () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    ChallengeService.parseNotebook.mockResolvedValue({
      ok: false,
      data: { error: 'Invalid notebook JSON format.' },
    });

    render(<NotebookSubmit task={task} challenge={challenge} />);

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['invalidjson'], 'my_solution.ipynb', { type: 'application/json' });

    fireEvent.change(fileInput, { target: { files: [validFile] } });

    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Invalid notebook JSON format.', 'error');
    });
  });

  it('handles parseNotebook network throw exception gracefully', async () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    ChallengeService.parseNotebook.mockRejectedValue(new Error('DNS failure'));

    render(<NotebookSubmit task={task} challenge={challenge} />);

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['{}'], 'my_solution.ipynb', { type: 'application/json' });

    fireEvent.change(fileInput, { target: { files: [validFile] } });

    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Network error parsing notebook.', 'error');
    });
  });

  it('verifies cell selection changes, submit button disabled checks, and execution submission calls', async () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    const cellsMock = [{ id: 1, type: 'code', source: 'import numpy as np' }];

    ChallengeService.parseNotebook.mockResolvedValue({
      ok: true,
      data: { filename: 'sol.ipynb', cells: cellsMock },
    });
    TaskService.submit.mockResolvedValue({ ok: true });

    render(<NotebookSubmit task={task} challenge={challenge} />);

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['{}'], 'sol.ipynb', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [validFile] } });

    // Wait for file parsing to complete and render the cells list
    await vi.waitFor(() => {
      expect(screen.getByText('Select Cells (0/1 code cells)')).toBeInTheDocument();
    });

    // Checkbox is unchecked by default
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).not.toBeChecked();

    // Select the cell by clicking its checkbox
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(screen.getByText('Select Cells (1/1 code cells)')).toBeInTheDocument();

    // Submit cells
    const submitBtn = screen.getByText(/Submit 1 cells? for Evaluation/i);
    fireEvent.click(submitBtn);

    expect(TaskService.submit).toHaveBeenCalledWith(1, [cellsMock[0]]);

    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Submission queued for evaluation!');
      // State reset check
      expect(screen.queryByText('Select Cells (0/1 code cells)')).not.toBeInTheDocument();
    });
  });
});
