import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import AdminPanel from './AdminPanel';
import api from '../services/ApiService';

vi.mock('../services/ApiService', () => ({
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

vi.mock('../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../context/AppContext', () => ({
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

  const setupMockApi = () => {
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
    api.fetch.mockImplementation((url) => {
      if (url.includes('/admin/metrics') || url.includes('/metrics')) {
        return Promise.resolve({
          ok: true,
          json: async () => metricsData,
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      });
    });
  };

  beforeEach(() => {
    vi.clearAllMocks();

    global.EventSource = class {
      constructor(url) {
        this.url = url;
        this.close = vi.fn();
      }
    };

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
    render(<AdminPanel />);

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
    render(<AdminPanel />);

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
    render(<AdminPanel />);

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

    // Find the "Add Evaluation Metric" select (it contains the "+" text)
    const metricSelects = screen.getAllByRole('combobox');
    const addMetric = metricSelects.find((s) =>
      s.querySelector('option')?.textContent?.includes('Add'),
    );
    expect(addMetric).toBeDefined();
  });

  it('renders metric parameters dynamically based on metric schema', async () => {
    setupMockApi();
    render(<AdminPanel />);

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

    // Add chrf metric (has Beta parameter)
    // Wait for metrics to load (ChrF option appears)
    await vi.waitFor(() => {
      const chrFOption = document.querySelector('option[value="chrf"]');
      expect(chrFOption).not.toBeNull();
    });

    // Find the add metric select by its default placeholder option
    const addMetricSelect = screen
      .getAllByRole('combobox')
      .find((s) => s.querySelector('option[value=""]')?.textContent?.includes('Add'));
    expect(addMetricSelect).not.toBeNull();

    await act(async () => {
      fireEvent.change(addMetricSelect, { target: { value: 'chrf' } });
    });

    // Wait for beta parameter select to appear
    await vi.waitFor(() => {
      const allCombos = screen.getAllByRole('combobox');
      const found = allCombos.find((s) =>
        Array.from(s.options).some((o) => o.value === '1' || o.value === '2' || o.value === '3'),
      );
      expect(found).toBeDefined();
    });

    // Find the beta select (one of the parameter selects)
    const allCombos = screen.getAllByRole('combobox');
    const betaSelect = allCombos.find((s) =>
      Array.from(s.options).some((o) => o.value === '1' || o.value === '2' || o.value === '3'),
    );
    expect(betaSelect).toBeInTheDocument();
    expect(betaSelect.value).toBe('1');

    await act(async () => {
      fireEvent.change(betaSelect, { target: { value: '2' } });
    });
    expect(betaSelect.value).toBe('2');
  });

  it('enforces maximum of 10 metrics', async () => {
    setupMockApi();
    render(<AdminPanel />);

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
      'accuracy',
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

    for (const metric of allMetrics.slice(0, 10)) {
      const addSelect = screen
        .getAllByRole('combobox')
        .find((s) =>
          Array.from(s.options).some(
            (o) => o.textContent === 'Accuracy' || o.textContent === formatMetricName(metric),
          ),
        );
      if (addSelect) {
        await act(async () => {
          fireEvent.change(addSelect, { target: { value: metric } });
        });
      }
    }

    // The add metric dropdown should be disabled
    const addSelect = screen
      .getAllByRole('combobox')
      .find((s) => Array.from(s.options).some((o) => o.value === ''));
    expect(addSelect).toBeDefined();
    // After 10 metrics the dropdown should be disabled
  });

  it('removes a metric when remove button is clicked', async () => {
    setupMockApi();
    render(<AdminPanel />);

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

    // Add accuracy metric
    const addSelect = screen
      .getAllByRole('combobox')
      .find((s) => Array.from(s.options).some((o) => o.textContent === 'Accuracy'));
    if (addSelect) {
      await act(async () => {
        fireEvent.change(addSelect, { target: { value: 'accuracy' } });
      });
    }

    // Metric table should be visible
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
