import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, act } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import { useAuth } from '../../../AuthContext';
import { useApp } from '../../../context/AppContext';
import ChallengeService from '../../../services/ChallengeService';
import TaskService from '../../../services/TaskService';
import NotebookSubmit from '../NotebookSubmit';

// Mock contexts
const { mockShowToast } = vi.hoisted(() => ({ mockShowToast: vi.fn() }));
vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: vi.fn() }),
}));

vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useNavigate: () => vi.fn(),
}));

vi.mock('../../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

// Mock services
vi.mock('../../../services/ChallengeService', () => ({
  default: {
    parseNotebook: vi.fn(),
  },
}));

vi.mock('../../../services/TaskService', () => ({
  default: {
    submit: vi.fn(),
    loadWorkspaceNotebook: vi.fn(),
    submitWorkspace: vi.fn(),
  },
}));

describe('NotebookSubmit Component', () => {
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

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    expect(screen.getByText('Judge / Admin Session Active')).toBeInTheDocument();
    expect(screen.queryByText('Submit Solution')).not.toBeInTheDocument();
  });

  it('renders competition closed banner if challenge is inactive', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    const inactiveChallenge = { ...challenge, is_active: false };
    renderWithProviders(<NotebookSubmit task={task} challenge={inactiveChallenge} />);
    expect(screen.getByText('Competition Closed')).toBeInTheDocument();
  });

  it('renders competition closed banner if challenge is archived', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    const archivedChallenge = { ...challenge, is_archived: true };
    renderWithProviders(<NotebookSubmit task={task} challenge={archivedChallenge} />);
    expect(screen.getByText('Competition Closed')).toBeInTheDocument();
  });

  it('renders upload panel normally for active competitor', () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    expect(screen.getByText('Submit Solution')).toBeInTheDocument();
    expect(screen.getByText('Upload Jupyter Notebook (.ipynb)')).toBeInTheDocument();
  });

  it('validates file extension upon upload selection', async () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    // Query file input element
    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);

    // Mock an invalid text file
    const invalidFile = new File(['print("hello")'], 'solution.py', { type: 'text/x-python' });
    fireEvent.change(fileInput, { target: { files: [invalidFile] } });
    await act(async () => {});

    expect(mockShowToast).toHaveBeenCalledWith('Only .ipynb files are supported.', 'error');
    expect(ChallengeService.parseNotebook).not.toHaveBeenCalled();
  });

  it('parses the same notebook again when it is picked a second time', async () => {
    useAuth.mockReturnValue({ currentUser: { role: 'competitor' } });
    ChallengeService.parseNotebook.mockResolvedValue({
      ok: true,
      data: { filename: 'my_solution.ipynb', cells: [] },
    });

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['{}'], 'my_solution.ipynb', { type: 'application/json' });
    const setValue = vi.spyOn(fileInput, 'value', 'set');
    fireEvent.change(fileInput, { target: { files: [validFile] } });
    await act(async () => {});
    expect(setValue).toHaveBeenCalledWith('');

    fireEvent.change(screen.getByLabelText(/Click to replace/i), {
      target: { files: [validFile] },
    });
    await act(async () => {});

    expect(ChallengeService.parseNotebook).toHaveBeenCalledTimes(2);
  });

  it('parses a notebook dropped onto the upload zone', async () => {
    useAuth.mockReturnValue({ currentUser: { role: 'competitor' } });
    ChallengeService.parseNotebook.mockResolvedValue({
      ok: true,
      data: { filename: 'dropped.ipynb', cells: [] },
    });

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    const zone = screen.getByText('Upload Jupyter Notebook (.ipynb)').closest('label');
    const droppedFile = new File(['{}'], 'dropped.ipynb', { type: 'application/json' });
    fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files: [droppedFile] } });
    await act(async () => {});

    expect(ChallengeService.parseNotebook).toHaveBeenCalledWith(10, droppedFile);
  });

  it('rejects a dropped file that is not a notebook', async () => {
    useAuth.mockReturnValue({ currentUser: { role: 'competitor' } });

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    const zone = screen.getByText('Upload Jupyter Notebook (.ipynb)').closest('label');
    const script = new File(['print(1)'], 'solution.py', { type: 'text/x-python' });
    fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files: [script] } });
    await act(async () => {});

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

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['{}'], 'my_solution.ipynb', { type: 'application/json' });

    fireEvent.change(fileInput, { target: { files: [validFile] } });
    await act(async () => {});

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

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['invalidjson'], 'my_solution.ipynb', { type: 'application/json' });

    fireEvent.change(fileInput, { target: { files: [validFile] } });
    await act(async () => {});

    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Invalid notebook JSON format.', 'rose');
    });
  });

  it('handles parseNotebook network throw exception gracefully', async () => {
    useAuth.mockReturnValue({
      currentUser: { role: 'competitor' },
    });

    ChallengeService.parseNotebook.mockRejectedValue(new Error('DNS failure'));

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['{}'], 'my_solution.ipynb', { type: 'application/json' });

    fireEvent.change(fileInput, { target: { files: [validFile] } });
    await act(async () => {});

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

    renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
    await act(async () => {});

    const fileInput = screen.getByLabelText(/Upload Jupyter Notebook/i);
    const validFile = new File(['{}'], 'sol.ipynb', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [validFile] } });
    await act(async () => {});

    // Wait for file parsing to complete and render the cells list
    await vi.waitFor(() => {
      expect(screen.getByText('Select Cells (0/1 code cells)')).toBeInTheDocument();
    });

    // Checkbox is unchecked by default
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).not.toBeChecked();

    // Select the cell by clicking its checkbox
    fireEvent.click(checkbox);
    await act(async () => {});
    expect(checkbox).toBeChecked();
    expect(screen.getByText('Select Cells (1/1 code cells)')).toBeInTheDocument();

    // Submit cells
    const submitBtn = screen.getByText(/Submit 1 cells? for Evaluation/i);
    fireEvent.click(submitBtn);
    await act(async () => {});

    expect(TaskService.submit).toHaveBeenCalledWith(1, [cellsMock[0]]);

    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Submission queued for evaluation!');
      // State reset check
      expect(screen.queryByText('Select Cells (0/1 code cells)')).not.toBeInTheDocument();
    });
  });

  describe('with workspaces', () => {
    const workspaceTask = { ...task, folder_name: 'task-a' };
    const workspaceChallenge = { ...challenge, workspaces_enabled: true };

    beforeEach(() => {
      useAuth.mockReturnValue({ currentUser: { role: 'competitor' } });
    });

    it('offers no workspace button without workspaces', () => {
      renderWithProviders(<NotebookSubmit task={task} challenge={challenge} />);
      expect(screen.queryByRole('button', { name: /Load from workspace/ })).toBeNull();
    });

    it('fills the cell picker from solution.ipynb in the workspace', async () => {
      TaskService.loadWorkspaceNotebook.mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          filename: 'solution.ipynb',
          cells: [
            { id: 0, type: 'markdown', source: '# Notes' },
            { id: 1, type: 'code', source: '# SUBMIT\nprint(1)' },
          ],
        },
      });
      renderWithProviders(<NotebookSubmit task={workspaceTask} challenge={workspaceChallenge} />);
      expect(
        screen.getByText('Reads solution.ipynb from task-a/ in your workspace.'),
      ).toBeInTheDocument();
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /Load from workspace/ }));
      });
      expect(TaskService.loadWorkspaceNotebook).toHaveBeenCalledWith(1);
      expect(await screen.findByText('solution.ipynb')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Submit 1 cell/ })).toBeEnabled();
    });

    it('explains a missing notebook next to the button', async () => {
      TaskService.loadWorkspaceNotebook.mockResolvedValue({
        ok: false,
        status: 404,
        data: {
          code: 'ERR_WORKSPACE_NOTEBOOK_MISSING',
          error: 'No solution.ipynb in task-a/ of your workspace.',
          folder: 'task-a',
        },
        res: { headers: { get: () => null } },
      });
      renderWithProviders(<NotebookSubmit task={workspaceTask} challenge={workspaceChallenge} />);
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /Load from workspace/ }));
      });
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'No solution.ipynb in task-a/ of your workspace.',
      );
    });

    it('waits out a platform failure of the notebook check', async () => {
      TaskService.loadWorkspaceNotebook.mockResolvedValue({
        ok: false,
        status: 503,
        data: { code: 'ERR_SUBMISSION_CHECK_FAILED', error: 'check failed' },
        res: { headers: { get: (name) => (name === 'Retry-After' ? '4' : null) } },
      });
      renderWithProviders(<NotebookSubmit task={workspaceTask} challenge={workspaceChallenge} />);
      const button = screen.getByRole('button', { name: /Load from workspace/ });
      await act(async () => {
        fireEvent.click(button);
      });
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The file could not be checked because of a platform problem. Please try again shortly.',
      );
      expect(screen.getByText('Try again in 4 seconds.')).toBeInTheDocument();
      expect(button).toBeDisabled();
    });

    it('shows the file submit card for a file task', () => {
      renderWithProviders(
        <NotebookSubmit
          task={{ ...workspaceTask, evaluation_mode: 'file' }}
          challenge={workspaceChallenge}
        />,
      );
      expect(screen.getByTestId('file-submit')).toBeInTheDocument();
      expect(screen.queryByText('Upload Jupyter Notebook (.ipynb)')).toBeNull();
    });
  });
});
