import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TaskManager from '../TaskManager';

vi.mock('../../../context/AppContext', () => ({
  useApp: () => ({ showToast: vi.fn() }),
}));

vi.mock('../../../hooks/useTaskMutations', () => ({
  useCreateTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('../TaskForm', () => ({
  default: ({ taskForm }) => (
    <span data-testid="public-eval-percentage">{taskForm.public_eval_percentage}</span>
  ),
}));

describe('TaskManager', () => {
  it('preserves a zero public evaluation percentage when editing', () => {
    render(
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
