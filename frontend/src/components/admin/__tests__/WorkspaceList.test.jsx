import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '../../../test-utils';
import WorkspaceList from '../WorkspaceList';
import EnvironmentService from '../../../services/EnvironmentService';

vi.mock('../../../services/EnvironmentService', () => ({
  default: { getWorkspaces: vi.fn() },
}));

const ROWS = [
  {
    user_id: 'u1',
    alias: 'Quiet-Falcon-a1b2',
    username: 'comp_maria',
    opened: true,
    created_at: '2027-05-01T09:05:00+03:00',
    last_launched_at: '2027-05-01T11:40:00+03:00',
    last_submission_at: '2027-05-01T11:50:00+03:00',
    last_submission_status: 'completed',
  },
  {
    user_id: 'u2',
    alias: 'Brave-Otter-c3d4',
    username: null,
    opened: false,
    created_at: null,
    last_launched_at: null,
    last_submission_at: null,
    last_submission_status: null,
  },
];

function renderList() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <WorkspaceList challengeId="c1" environmentId="e1" timezone="Europe/Sofia" />
    </QueryClientProvider>,
  );
}

describe('WorkspaceList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    EnvironmentService.getWorkspaces.mockResolvedValue({
      ok: true,
      status: 200,
      data: { workspaces: ROWS },
    });
  });

  it('loads the list only when it is opened', async () => {
    renderList();
    expect(EnvironmentService.getWorkspaces).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Show student workspaces' }));
    expect(await screen.findByText('Quiet-Falcon-a1b2')).toBeInTheDocument();
    expect(EnvironmentService.getWorkspaces).toHaveBeenCalledWith('c1', 'e1');
    expect(screen.getByText('1 of 2 students have opened their workspace')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide student workspaces' })).toBeInTheDocument();
  });

  it('shows the username only when the API sends it, and each row state', async () => {
    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Show student workspaces' }));
    expect(await screen.findByText('comp_maria')).toBeInTheDocument();
    expect(screen.getByText('Brave-Otter-c3d4')).toBeInTheDocument();
    expect(screen.getByText('Not opened')).toBeInTheDocument();
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Times in Europe/Sofia')).toBeInTheDocument();
  });

  it('says when no student is registered', async () => {
    EnvironmentService.getWorkspaces.mockResolvedValue({
      ok: true,
      status: 200,
      data: { workspaces: [] },
    });
    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Show student workspaces' }));
    expect(await screen.findByText('No students are registered yet.')).toBeInTheDocument();
  });
});
