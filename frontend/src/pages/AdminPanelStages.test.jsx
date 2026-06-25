import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import AdminPanel from './AdminPanel';

// Mock AuthContext
vi.mock('../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock AppContext
vi.mock('../context/AppContext', () => ({
  useApp: vi.fn(),
}));

describe('AdminPanel - Stages and Finalization Actions', () => {
  const mockShowToast = vi.fn();
  const mockSetSelectedChallengeById = vi.fn();
  const mockFetchChallenges = vi.fn();
  const mockConfirm = vi.fn();

  const mockStagesChallenge = {
    id: 1,
    title: 'Challenge Alpha',
    is_active: true,
    is_archived: false,
    end_time: '2026-06-13T12:00:00Z',
    stages: [
      {
        id: 10,
        title: 'Stage 1',
        stage_number: 1,
        start_time: '2026-06-13T10:00:00Z',
        end_time: '2026-06-13T12:00:00Z',
        is_finalized: false,
      },
    ],
    tasks: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();

    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'jury_user', role: 'jury' },
    });

    useApp.mockReturnValue({
      challenges: [mockStagesChallenge],
      selectedChallenge: mockStagesChallenge,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });

    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/challenges')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            items: [mockStagesChallenge],
            total: 1,
            pages: 1,
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      });
    });
  });

  it('renders stages list in the challenge view', async () => {
    render(<AdminPanel />);
    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });
    expect(screen.getByText(/Stage 1\s*:\s*Stage 1/)).toBeInTheDocument();
  });

  it('triggers stage creation modal when "+ Add Stage" is clicked and handles submission', async () => {
    render(<AdminPanel />);

    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });

    const addStageBtn = screen.getByText('Add Stage');
    expect(addStageBtn).toBeInTheDocument();

    fireEvent.click(addStageBtn);

    expect(screen.getByText('Create New Stage')).toBeInTheDocument();

    const titleInput = screen.getByLabelText(/Stage Title/i);
    const stageNumInput = screen.getByLabelText(/Stage Number/i);
    const startInput = screen.getByLabelText(/Start Time/i);
    const endInput = screen.getByLabelText(/End Time/i);

    fireEvent.change(titleInput, { target: { value: 'Stage 2' } });
    fireEvent.change(stageNumInput, { target: { value: '2' } });
    fireEvent.change(startInput, { target: { value: '2026-06-13T10:00' } });
    fireEvent.change(endInput, { target: { value: '2026-06-13T12:00' } });

    const submitBtn = screen.getByText('Create Stage');

    await act(async () => {
      fireEvent.click(submitBtn);
    });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1/stages'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          title: 'Stage 2',
          stage_number: 2,
          start_time: '2026-06-13T10:00',
          end_time: '2026-06-13T12:00',
        }),
      }),
    );

    expect(mockShowToast).toHaveBeenCalledWith('Stage created successfully!');
  });

  it('triggers stage editing and submits update', async () => {
    render(<AdminPanel />);

    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });

    const stageRow = screen.getByText(/Stage 1\s*:\s*Stage 1/).closest('div').parentElement;
    const editBtn = within(stageRow).getByRole('button', { name: 'Edit' });
    fireEvent.click(editBtn);

    expect(screen.getByText('Edit Stage: Stage 1')).toBeInTheDocument();

    const titleInput = screen.getByLabelText(/Stage Title/i);
    fireEvent.change(titleInput, { target: { value: 'Stage 1 Renamed' } });

    const saveBtn = screen.getByRole('button', { name: 'Save Changes' });

    await act(async () => {
      fireEvent.click(saveBtn);
    });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1/stages/10'),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          title: 'Stage 1 Renamed',
          stage_number: 1,
          start_time: '2026-06-13T10:00',
          end_time: '2026-06-13T12:00',
          reveal_results: false,
        }),
      }),
    );

    expect(mockShowToast).toHaveBeenCalledWith('Stage updated successfully!');
  });

  it('triggers stage deletion API call when confirmed', async () => {
    mockConfirm.mockResolvedValue(true);
    render(<AdminPanel />);

    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });

    const stageRow = screen.getByText(/Stage 1\s*:\s*Stage 1/).closest('div').parentElement;
    const deleteBtn = within(stageRow).getByRole('button', { name: 'Delete' });

    await act(async () => {
      fireEvent.click(deleteBtn);
    });

    expect(mockConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Delete Stage',
      }),
    );

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1/stages/10'),
      expect.objectContaining({
        method: 'DELETE',
      }),
    );

    expect(mockShowToast).toHaveBeenCalledWith('Stage "Stage 1" deleted.');
  });

  it('triggers stage finalization modal and submits configuration', async () => {
    render(<AdminPanel />);

    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });

    const stageRow = screen.getByText(/Stage 1\s*:\s*Stage 1/).closest('div').parentElement;
    const finalizeBtn = within(stageRow).getByRole('button', { name: 'Finalize' });
    fireEvent.click(finalizeBtn);

    expect(screen.getByText('Finalize Stage: Stage 1')).toBeInTheDocument();

    const submitBtn = screen.getByRole('button', { name: 'Finalize Stage' });

    await act(async () => {
      fireEvent.click(submitBtn);
    });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1/stages/10/finalize'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          finalize_type: 'visible',
          reveal_public: true,
          reveal_private: false,
          reveal_points: false,
        }),
      }),
    );

    expect(mockShowToast).toHaveBeenCalledWith('Stage finalized successfully!');
  });

  it('disables challenge finalization button if any stage is unfinalized', async () => {
    render(<AdminPanel />);

    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });

    // Since mockStagesChallenge has an unfinalized stage (is_finalized: false),
    // the "Finalize Challenge" button should be disabled
    const finalizeChallengeBtn = screen.getAllByRole('button', { name: /Finalize/i })[0];
    expect(finalizeChallengeBtn).toBeDisabled();
    expect(finalizeChallengeBtn).toHaveAttribute('title', 'All stages must be finalized first');
  });

  it('allows challenge finalization when all stages are finalized', async () => {
    const mockFinalizedChallenge = {
      ...mockStagesChallenge,
      stages: [
        {
          id: 10,
          title: 'Stage 1',
          stage_number: 1,
          start_time: '2026-06-13T10:00:00Z',
          end_time: '2026-06-13T12:00:00Z',
          is_finalized: true,
        },
      ],
    };

    useApp.mockReturnValue({
      challenges: [mockFinalizedChallenge],
      selectedChallenge: mockFinalizedChallenge,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });

    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/challenges')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            items: [mockFinalizedChallenge],
            total: 1,
            pages: 1,
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      });
    });

    render(<AdminPanel />);

    await vi.waitFor(() => {
      expect(screen.getByText('Stages in this Competition (1)')).toBeInTheDocument();
    });

    // The "Finalize" button should be enabled now
    const finalizeChallengeBtn = screen.getAllByRole('button', { name: /Finalize/i })[0];
    expect(finalizeChallengeBtn).not.toBeDisabled();

    fireEvent.click(finalizeChallengeBtn);

    expect(screen.getByText(/Finalize Competition:/i)).toBeInTheDocument();

    const confirmBtn = screen.getByRole('button', { name: 'Finalize' });

    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/challenges/1/finalize'),
      expect.objectContaining({
        method: 'POST',
      }),
    );

    expect(mockShowToast).toHaveBeenCalledWith('Scores finalized and de-anonymized!');
  });
});
