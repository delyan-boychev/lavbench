import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
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

describe('AdminPanel - Unified Parquet Task Configuration', () => {
  const mockShowToast = vi.fn();
  const mockSetSelectedChallengeById = vi.fn();
  const mockFetchChallenges = vi.fn();
  const mockConfirm = vi.fn();

  const mockChallenge = {
    id: 1,
    title: 'IMDB Challenge',
    is_active: true,
    is_archived: false,
    stages: [],
    tasks: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    
    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'admin', role: 'admin' },
      token: 'valid-admin-token',
    });

    useApp.mockReturnValue({
      challenges: [mockChallenge],
      selectedChallenge: mockChallenge,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
  });

  it('renders task type dropdown and shows metrics checklist upon selection', async () => {
    render(<AdminPanel />);

    // Open Add Task modal
    const addTaskBtn = screen.getByText('+ Add Task');
    expect(addTaskBtn).toBeInTheDocument();
    fireEvent.click(addTaskBtn);

    // Verify task type dropdown is rendered
    const taskTypeSelect = screen.getByLabelText(/Task Type \/ Modality Group/i);
    expect(taskTypeSelect).toBeInTheDocument();
    expect(taskTypeSelect.value).toBe('');

    // Change Task Type to classification
    await act(async () => {
      fireEvent.change(taskTypeSelect, { target: { value: 'classification' } });
    });
    expect(taskTypeSelect.value).toBe('classification');

    // Verify modality metrics container and checkboxes appear
    expect(await screen.findByText('Configure Modality Metrics')).toBeInTheDocument();
    expect(await screen.findByText('Accuracy')).toBeInTheDocument();
    expect(screen.getByText('F1 Macro')).toBeInTheDocument();
    expect(screen.getByText('Precision Macro')).toBeInTheDocument();
    expect(screen.getByText('Recall Macro')).toBeInTheDocument();

    // Verify ground-truth callout appears with required columns
    expect(screen.getByText('Required File Schemas')).toBeInTheDocument();
    expect(screen.getByText(/Submission Format/i)).toBeInTheDocument();
    expect(screen.getByText(/submission.parquet/i)).toBeInTheDocument();
    expect(screen.getByText(/Ground Truth Format/i)).toBeInTheDocument();
    expect(screen.getByText(/labels.parquet/i)).toBeInTheDocument();
  });

  it('handles metric selection toggling and weight updates', async () => {
    render(<AdminPanel />);

    const addTaskBtn = screen.getByText('+ Add Task');
    fireEvent.click(addTaskBtn);

    const taskTypeSelect = screen.getByLabelText(/Task Type \/ Modality Group/i);
    await act(async () => {
      fireEvent.change(taskTypeSelect, { target: { value: 'classification' } });
    });

    // Accuracy checkbox should be checked by default
    const accuracyCheckbox = await screen.findByRole('checkbox', { name: /accuracy/i });
    expect(accuracyCheckbox).toBeChecked();

    // Weight input for accuracy should be visible with default value 1
    const metricsContainer = screen.getByTestId('modality-metrics-config');
    const weightInput = metricsContainer.querySelector('input[type="number"]');
    expect(weightInput).toBeInTheDocument();
    expect(weightInput.value).toBe('1');

    // Change weight to 2.5
    await act(async () => {
      fireEvent.change(weightInput, { target: { value: '2.5' } });
    });
    expect(weightInput.value).toBe('2.5');

    // Toggle f1_macro checkbox
    const f1MacroCheckbox = screen.getByRole('checkbox', { name: /f1 macro/i });
    expect(f1MacroCheckbox).not.toBeChecked();

    await act(async () => {
      fireEvent.click(f1MacroCheckbox);
    });
    expect(f1MacroCheckbox).toBeChecked();

    // Verify multiple weight inputs are now rendered
    const weightInputs = metricsContainer.querySelectorAll('input[type="number"]');
    expect(weightInputs).toHaveLength(2);
  });

  it('enforces a maximum of 5 metrics per task group', async () => {
    render(<AdminPanel />);

    const addTaskBtn = screen.getByText('+ Add Task');
    fireEvent.click(addTaskBtn);

    const taskTypeSelect = screen.getByLabelText(/Task Type \/ Modality Group/i);
    await act(async () => {
      fireEvent.change(taskTypeSelect, { target: { value: 'classification' } });
    });

    // Toggle f1_micro, f1_weighted, precision_micro, precision_weighted to make total 5 checked metrics
    const extraMetrics = ['f1 micro', 'f1 weighted', 'precision micro', 'precision weighted'];
    for (const mName of extraMetrics) {
      const checkbox = screen.getByRole('checkbox', { name: new RegExp(mName, 'i') });
      await act(async () => {
        fireEvent.click(checkbox);
      });
    }

    // Now 5 metrics are checked (accuracy + 4 above). Other checkboxes should be disabled.
    const recallMicroCheckbox = screen.getByRole('checkbox', { name: /recall micro/i });
    expect(recallMicroCheckbox).toBeDisabled();
    expect(screen.getByText(/Maximum limit of 5 metrics reached/i)).toBeInTheDocument();
  });

  it('renders and allows customizing metric options', async () => {
    render(<AdminPanel />);

    const addTaskBtn = screen.getByText('+ Add Task');
    fireEvent.click(addTaskBtn);

    const taskTypeSelect = screen.getByLabelText(/Task Type \/ Modality Group/i);

    // Change Task Type to translation_summ to test chrf specific Beta input
    await act(async () => {
      fireEvent.change(taskTypeSelect, { target: { value: 'translation_summ' } });
    });

    // Toggle chrf
    const chrfCheckbox = await screen.findByRole('checkbox', { name: /chrf/i });
    await act(async () => {
      fireEvent.click(chrfCheckbox);
    });

    // Verify Beta selectbox is rendered and defaults to 3
    const betaSelect = screen.getByRole('combobox', { name: /beta/i });
    expect(betaSelect).toBeInTheDocument();
    expect(betaSelect.value).toBe('3');

    await act(async () => {
      fireEvent.change(betaSelect, { target: { value: '2' } });
    });
    expect(betaSelect.value).toBe('2');

    // Change Task Type to keypoints to test PCK specific Threshold input
    await act(async () => {
      fireEvent.change(taskTypeSelect, { target: { value: 'keypoints' } });
    });

    // Toggle pck
    const pckCheckbox = await screen.findByRole('checkbox', { name: /pck/i });
    await act(async () => {
      fireEvent.click(pckCheckbox);
    });

    // Verify Threshold selectbox is rendered and defaults to 0.05
    const thresholdSelect = screen.getByRole('combobox', { name: /threshold/i });
    expect(thresholdSelect).toBeInTheDocument();
    expect(thresholdSelect.value).toBe('0.05');

    await act(async () => {
      fireEvent.change(thresholdSelect, { target: { value: '0.1' } });
    });
    expect(thresholdSelect.value).toBe('0.1');

    // Change Task Type to retrieval to test ndcg_k/recall_k custom K selectbox
    await act(async () => {
      fireEvent.change(taskTypeSelect, { target: { value: 'retrieval' } });
    });

    // Verify K selectbox is rendered (since ndcg_k is checked by default) and defaults to 10
    const kSelect = screen.getByRole('combobox', { name: /^k$/i });
    expect(kSelect).toBeInTheDocument();
    expect(kSelect.value).toBe('10');

    await act(async () => {
      fireEvent.change(kSelect, { target: { value: '20' } });
    });
    expect(kSelect.value).toBe('20');
  });
});
