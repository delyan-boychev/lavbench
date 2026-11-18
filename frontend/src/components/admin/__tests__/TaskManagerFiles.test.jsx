import React from 'react';
import { screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TaskManager from '../TaskManager';
import { renderWithProviders } from '../../../test-utils';

const { mockUpdate, mockShowToast } = vi.hoisted(() => ({
  mockUpdate: vi.fn(),
  mockShowToast: vi.fn(),
}));

vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: vi.fn() }),
}));

vi.mock('../../../hooks/useTaskMutations', () => ({
  useCreateTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateTask: () => ({ mutateAsync: mockUpdate, isPending: false }),
}));

const task = {
  id: 7,
  title: 'Task',
  challenge_id: 1,
  baseline_notebook_path: 'tasks/7/baseline.ipynb',
  files: [
    { filename: 'baseline.ipynb', type: 'baseline', size_bytes: 100 },
    { filename: 'labels.parquet', type: 'data', size_bytes: 100 },
    { filename: 'train.csv', type: 'data', size_bytes: 100 },
  ],
};

const renderEditor = () =>
  renderWithProviders(
    <TaskManager
      mode="edit"
      initialTask={task}
      challenges={[{ id: 1, title: 'C', stages: [] }]}
      selectedChallenge={{ id: 1, title: 'C' }}
      availableMetrics={{}}
      onClose={vi.fn()}
    />,
  );

describe('TaskManager file deletions', () => {
  beforeEach(() => {
    mockUpdate.mockReset();
    mockUpdate.mockResolvedValue({ ok: true, data: {} });
    mockShowToast.mockReset();
  });

  it('sends a removed data file and a replaced baseline', async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole('button', { name: /Files/ }));

    const row = screen.getByTestId('existing-file-train.csv');
    await user.click(within(row).getByRole('button', { name: 'Delete' }));

    const notebook = new File(['{}'], 'new_baseline.ipynb', { type: 'application/json' });
    const input = document.querySelector('input[type="file"]');
    await user.upload(input, notebook);

    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const formData = mockUpdate.mock.calls[0][0].formData;
    expect(JSON.parse(formData.get('deleted_files'))).toEqual(['train.csv']);
    expect(formData.get('baseline_notebook').name).toBe('new_baseline.ipynb');
  });

  it('keeps a deleted baseline from saving without a replacement', async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole('button', { name: /Files/ }));

    const baselineRow = screen.getByText('baseline.ipynb').closest('div.flex.items-center');
    await user.click(within(baselineRow.parentElement).getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(await screen.findByText('Baseline notebook is required.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Files/ })).toHaveAttribute('aria-pressed', 'true');
    expect(mockUpdate).not.toHaveBeenCalled();
    expect(mockShowToast).not.toHaveBeenCalled();
  });
});
