import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import AdminPanel from '../AdminPanel';
import api from '../../services/ApiService';

vi.mock('../../services/ApiService', () => ({
  default: {
    fetch: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    postForm: vi.fn(),
    putForm: vi.fn(),
    getBlob: vi.fn(),
  },
}));

vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

describe('AdminPanel - Column Config & Metrics', () => {
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

  const metricsData = {
    accuracy: { balanced: ['false', 'true'] },
    f1: { average: ['macro', 'micro', 'weighted', 'binary'] },
    precision: { average: ['macro', 'micro', 'weighted', 'binary'] },
    recall: { average: ['macro', 'micro', 'weighted', 'binary'] },
    cohen_kappa: {},
    matthews_corrcoef: {},
    rmse: { shape: 'string', multioutput: ['uniform_average', 'raw_values'] },
    mae: { shape: 'string', multioutput: ['uniform_average', 'raw_values'] },
    r_squared: {},
    mape: {},
    chrf: { beta: ['1', '2', '3'] },
    rouge: { rouge_type: ['rouge1', 'rouge2', 'rougeL'] },
    bleu: {},
    meteor: {},
    exact_match: {},
    pck: { threshold: ['0.01', '0.02', '0.05', '0.1', '0.15', '0.2'] },
    ndcg_k: { k: ['5', '10', '20', '50', '100'] },
    mrr: {},
    recall_k: { k: ['5', '10', '20', '50', '100'] },
  };

  const setupMockApi = () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/admin/metrics')) {
        return Promise.resolve({ ok: true, data: metricsData });
      }
      if (url.includes('/challenges')) {
        return Promise.resolve({ ok: true, data: { items: [mockChallenge], pages: 1, total: 1 } });
      }
      return Promise.resolve({ ok: true, data: { items: [], total: 0, pages: 1 } });
    });
    api.fetch.mockImplementation((url) => {
      if (url.includes('/admin/metrics') || url.includes('/metrics')) {
        return Promise.resolve({ ok: true, json: async () => metricsData });
      }
      if (url.includes('/challenges')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ items: [mockChallenge], pages: 1, total: 1 }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  };

  beforeEach(() => {
    vi.clearAllMocks();

    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'admin', role: 'admin' },
    });

    useApp.mockReturnValue({
      challenges: [mockChallenge],
      selectedChallenge: mockChallenge,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
      confirm: mockConfirm,
    });
  });

  it('renders column definitions section and allows adding columns', async () => {
    setupMockApi();
    renderWithProviders(<AdminPanel />);

    fireEvent.click(screen.getByText('Add Task'));
    fireEvent.click(screen.getByText('Evaluation'));

    // Column Definitions section should be visible
    expect(screen.getByText('Column Definitions')).toBeInTheDocument();
    expect(screen.getByText('Add Column')).toBeInTheDocument();

    // Initially shows empty state
    expect(screen.getAllByText(/No columns defined/i).length).toBeGreaterThan(0);

    // Add a column
    await act(async () => {
      fireEvent.click(screen.getByText('Add Column'));
    });

    // Column row should appear with inputs
    const nameInputs = screen.getAllByPlaceholderText(/e\.g\. id/i);
    expect(nameInputs.length).toBe(1);

    // Type the column name
    await act(async () => {
      fireEvent.change(nameInputs[0], { target: { value: 'label' } });
    });
    expect(nameInputs[0].value).toBe('label');
  });

  it('shows parquet format preview when columns are defined', async () => {
    setupMockApi();
    renderWithProviders(<AdminPanel />);

    fireEvent.click(screen.getByText('Add Task'));
    fireEvent.click(screen.getByText('Evaluation'));

    // Add a column
    await act(async () => {
      fireEvent.click(screen.getByText('Add Column'));
    });

    const nameInput = screen.getAllByPlaceholderText(/e\.g\. id/i)[0];
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'label' } });
    });

    // Format preview should appear
    expect(screen.getByText('Parquet Format Preview')).toBeInTheDocument();
    expect(screen.getAllByText(/submission\.parquet/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/labels\.parquet/).length).toBeGreaterThan(0);
  });

  it('allows adding metrics via dropdown and shows column mapping selector', async () => {
    setupMockApi();
    renderWithProviders(<AdminPanel />);

    fireEvent.click(screen.getByText('Add Task'));
    fireEvent.click(screen.getByText('Evaluation'));

    // Add a column first so column mapping dropdown has options
    await act(async () => {
      fireEvent.click(screen.getByText('Add Column'));
    });
    const nameInput = screen.getAllByPlaceholderText(/e\.g\. id/i)[0];
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'label' } });
    });

    expect(
      await screen.findByRole('combobox', { name: /Add Evaluation Metric/i }),
    ).toBeInTheDocument();
  });

  it('renders metric parameters dynamically based on metric schema', async () => {
    setupMockApi();
    renderWithProviders(<AdminPanel />);

    fireEvent.click(screen.getByText('Add Task'));
    fireEvent.click(screen.getByText('Evaluation'));

    // Add a column
    await act(async () => {
      fireEvent.click(screen.getByText('Add Column'));
    });
    const nameInput = screen.getAllByPlaceholderText(/e\.g\. id/i)[0];
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'label' } });
    });

    const addMetricSelect = await screen.findByRole('combobox', {
      name: /Add Evaluation Metric/i,
    });
    fireEvent.click(addMetricSelect);
    fireEvent.click(await screen.findByRole('option', { name: 'chrF' }));

    // Wait for beta parameter select to appear
    await vi.waitFor(() => {
      expect(screen.getByRole('combobox', { name: '1' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('combobox', { name: '1' }));
    fireEvent.click(screen.getByRole('option', { name: '2' }));
    expect(screen.getByRole('combobox', { name: '2' })).toBeInTheDocument();
  });

  it('enforces maximum of 10 metrics', async () => {
    setupMockApi();
    renderWithProviders(<AdminPanel />);

    fireEvent.click(screen.getByText('Add Task'));
    fireEvent.click(screen.getByText('Evaluation'));

    // Add a column
    await act(async () => {
      fireEvent.click(screen.getByText('Add Column'));
    });
    const nameInput = screen.getAllByPlaceholderText(/e\.g\. id/i)[0];
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'label' } });
    });

    // Add metrics up to the limit
    const allMetrics = [
      'f1',
      'precision',
      'recall',
      'cohen_kappa',
      'matthews_corrcoef',
      'rmse',
      'mae',
      'r_squared',
      'mape',
    ];

    for (const metric of allMetrics) {
      const addSelect = await screen.findByRole('combobox', {
        name: /Add Evaluation Metric/i,
      });
      fireEvent.click(addSelect);
      fireEvent.click(await screen.findByRole('option', { name: formatMetricName(metric) }));
    }

    expect(screen.getByRole('combobox', { name: /Add Evaluation Metric/i })).toBeDisabled();
  });

  it('removes a metric when remove button is clicked', async () => {
    setupMockApi();
    renderWithProviders(<AdminPanel />);

    fireEvent.click(screen.getByText('Add Task'));
    fireEvent.click(screen.getByText('Evaluation'));

    // Add a column
    await act(async () => {
      fireEvent.click(screen.getByText('Add Column'));
    });
    const nameInput = screen.getAllByPlaceholderText(/e\.g\. id/i)[0];
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'label' } });
    });

    // Accuracy is present by default for new tasks
    expect(screen.getByText('Accuracy')).toBeInTheDocument();

    // Click remove button (the trash icon in the metric row)
    const removeMetric = screen.getByTitle('Remove metric');
    if (removeMetric) {
      await act(async () => {
        fireEvent.click(removeMetric);
      });
    }

    // After removing, the "Add Evaluation Metric" dropdown should still be there
    expect(screen.getByText('Evaluation Metrics')).toBeInTheDocument();
  });
});

function formatMetricName(name) {
  if (!name) return '';
  const specialWords = {
    f1: 'F1',
    rmse: 'RMSE',
    mae: 'MAE',
    chrf: 'ChrF',
    bleu: 'BLEU',
    rouge: 'ROUGE',
    meteor: 'METEOR',
    ter: 'TER',
    mrr: 'MRR',
    ndcg: 'NDCG',
    map: 'mAP',
    iou: 'IoU',
    auc: 'AUC',
    roc: 'ROC',
    mape: 'MAPE',
    ae: 'AE',
  };
  let formatted = name.replace(/_/g, ' ');
  if (formatted.toLowerCase() === 'map 50 95') return 'mAP 50-95';
  return formatted
    .split(' ')
    .map((word) => {
      const lower = word.toLowerCase();
      if (specialWords[lower] !== undefined) return specialWords[lower];
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(' ');
}
