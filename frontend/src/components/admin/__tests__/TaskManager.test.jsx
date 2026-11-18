import React from 'react';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import { describe, expect, it, vi } from 'vitest';
import TaskManager from '../TaskManager';

const { mockShowToast } = vi.hoisted(() => ({ mockShowToast: vi.fn() }));
vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: vi.fn() }),
}));

vi.mock('../../../context/AppContext', () => ({
  useApp: () => ({ showToast: vi.fn() }),
}));

vi.mock('../../../hooks/useTaskMutations', () => ({
  useCreateTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetEmergencyUpload: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRemoveHfZip: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteTaskFile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useInvalidateTaskData: () => vi.fn(),
}));

vi.mock('../TaskForm', () => ({
  default: ({ taskForm }) => (
    <span data-testid="public-eval-percentage">{taskForm.public_eval_percentage}</span>
  ),
}));

describe('TaskManager', () => {
  it('preserves a zero public evaluation percentage when editing', () => {
    renderWithProviders(
      <TaskManager
        mode="edit"
        initialTask={{ id: 1, title: 'Task', public_eval_percentage: 0 }}
        challenges={[]}
        selectedChallenge={null}
        availableMetrics={{}}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByTestId('public-eval-percentage')).toHaveTextContent('0');
  });
});
