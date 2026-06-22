import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TaskForm from '../TaskForm';

const mockFormatMetricName = vi.fn((name) => name.replace(/_/g, ' '));
const mockFormatDateTime = vi.fn(() => '2025-01-01 00:00');

const defaultTaskForm = {
  title: '',
  description: '',
  ram_limit_mb: '',
  time_limit_sec: '',
  gpu_required: true,
  base_docker_image: '',
  apt_packages: '',
  pip_requirements: '',
  ban_magic_commands: false,
  banned_imports: '',
  whitelisted_imports: '',
  metrics_config: '',
  hf_datasets_raw: '',
  hf_models_raw: '',
  hf_api_key: '',
  public_eval_percentage: 30,
  max_submissions_per_period: '',
  submission_period_hours: '',
  stage_id: '',
};

const defaultProps = {
  taskForm: { ...defaultTaskForm },
  setTaskForm: vi.fn(),
  isCreatingTask: true,
  editingTask: null,
  setEditingTask: vi.fn(),
  setIsCreatingTask: vi.fn(),
  handleSaveCreateTask: vi.fn((e) => e.preventDefault()),
  handleSaveUpdateTask: vi.fn((e) => e.preventDefault()),
  challenges: [],
  selectedChallenge: null,
  availableMetrics: {},
  formatMetricName: mockFormatMetricName,
  taskFiles: [],
  setTaskFiles: vi.fn(),
  baselineFile: null,
  setBaselineFile: vi.fn(),
  formatDateTime: mockFormatDateTime,
  savingTask: false,
};

function renderTaskForm(props = {}) {
  return render(<TaskForm {...defaultProps} {...props} />);
}

// Mock FileUploader
vi.mock('../../ui/FileUploader', () => ({
  default: ({ label, files: _files, onChange, accept, multiple, ...rest }) => (
    <div data-testid={`fileuploader-${label?.replace(/\s+/g, '-').toLowerCase()}`}>
      <span data-testid="fileuploader-label">{label}</span>
      <span data-testid="fileuploader-accept">{accept}</span>
      <span data-testid="fileuploader-multiple">{String(!!multiple)}</span>
      <span data-testid="fileuploader-files-count">{_files?.length ?? 0}</span>
      <button
        data-testid="fileuploader-onchange"
        onClick={() => onChange([{ name: 'test.parquet', size: 1024 }])}
      >
        trigger-change
      </button>
      {rest.existingFiles?.map((f) => (
        <div key={f.filename} data-testid={`existing-file-${f.filename}`}>
          {f.filename} {f._deleted ? '(deleted)' : ''}
        </div>
      ))}
      {rest.onRemoveExisting && (
        <button
          data-testid="fileuploader-onremove"
          onClick={() => rest.onRemoveExisting('labels.parquet')}
        >
          trigger-remove
        </button>
      )}
    </div>
  ),
}));

// Mock TabScrollContainer to just render children
vi.mock('../../ui/TabScrollContainer', () => ({
  default: ({ children }) => <div data-testid="tab-scroll-container">{children}</div>,
}));

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Pencil: () => <span data-testid="icon-pencil" />,
  BarChart3: () => <span data-testid="icon-barchart" />,
  Lock: () => <span data-testid="icon-lock" />,
  Box: () => <span data-testid="icon-box" />,
  Folder: () => <span data-testid="icon-folder" />,
  Plus: () => <span data-testid="icon-plus" />,
}));

describe('TaskForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('General Tab (default)', () => {
    it('renders title input', () => {
      renderTaskForm();
      const titleInput = document.querySelector('input[id="task-title"]');
      expect(titleInput).toBeInTheDocument();
      expect(screen.getByText('Task Title')).toBeInTheDocument();
    });

    it('renders stage dropdown selector', () => {
      renderTaskForm();
      expect(screen.getByText('Competition Stage (Optional)')).toBeInTheDocument();
    });

    it('renders description textarea', () => {
      renderTaskForm();
      const textarea = document.querySelector('textarea');
      expect(textarea).toBeInTheDocument();
      expect(screen.getByText('Task Description (Supports Markdown)')).toBeInTheDocument();
    });

    it('renders max submissions per period input', () => {
      renderTaskForm();
      expect(screen.getByText('Max Submissions limit')).toBeInTheDocument();
    });

    it('renders submission period hours input', () => {
      renderTaskForm();
      expect(screen.getByText('Submission limit period (Hours)')).toBeInTheDocument();
    });

    it('pre-fills values from initialData', () => {
      const taskForm = {
        ...defaultTaskForm,
        title: 'My Test Task',
        description: 'Test description content',
        max_submissions_per_period: '5',
        submission_period_hours: '24',
        stage_id: '1',
      };
      renderTaskForm({ taskForm, editingTask: { id: 1, title: 'My Test Task', challenge_id: 1 } });
      expect(screen.getByDisplayValue('My Test Task')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Test description content')).toBeInTheDocument();
      expect(screen.getByDisplayValue('5')).toBeInTheDocument();
      expect(screen.getByDisplayValue('24')).toBeInTheDocument();
    });
  });

  describe('Tab Navigation', () => {
    it('renders all five tab buttons with correct labels', () => {
      renderTaskForm();
      expect(screen.getByText('General')).toBeInTheDocument();
      expect(screen.getByText('Evaluation')).toBeInTheDocument();
      expect(screen.getByText('Sandbox')).toBeInTheDocument();
      expect(screen.getByText('Environment')).toBeInTheDocument();
      expect(screen.getByText('Files')).toBeInTheDocument();
    });

    it('switches to Evaluation tab when clicked', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('Column Definitions')).toBeInTheDocument();
      expect(screen.queryByLabelText('Task Title *')).not.toBeInTheDocument();
    });

    it('switches to Sandbox tab when clicked', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(screen.getByText('Resource Limits')).toBeInTheDocument();
    });

    it('switches to Environment tab when clicked', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('Docker Sandbox')).toBeInTheDocument();
    });

    it('switches to Files tab when clicked', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Files'));
      // Files tab renders FileUploader with "Ground Truth & Resources" label
      expect(screen.getByText('Ground Truth & Resources')).toBeInTheDocument();
    });
  });

  describe('Evaluation Tab', () => {
    it('renders column definitions section', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('Column Definitions')).toBeInTheDocument();
    });

    it('renders public eval split slider', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      const slider = screen.getByDisplayValue('30');
      expect(slider).toBeInTheDocument();
      expect(slider).toHaveAttribute('type', 'range');
    });

    it('adds a column when Add Column is clicked', () => {
      const setTaskForm = vi.fn();
      renderTaskForm({ setTaskForm });
      fireEvent.click(screen.getByText('Evaluation'));
      fireEvent.click(screen.getByText('Add Column'));

      expect(setTaskForm).toHaveBeenCalled();
      const call = setTaskForm.mock.calls[0][0];
      expect(call.metrics_config).toBeTruthy();
      const parsed = JSON.parse(call.metrics_config);
      expect(parsed._columns).toHaveLength(1);
      expect(parsed._columns[0]).toEqual({ name: '', type: 'string', desc: '' });
    });

    it('renders evaluation metrics section', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('Evaluation Metrics')).toBeInTheDocument();
    });

    it('renders parquet preview when columns exist', () => {
      const taskForm = {
        ...defaultTaskForm,
        metrics_config: JSON.stringify({
          _columns: [{ name: 'id', type: 'string', desc: 'identifier' }],
        }),
      };
      renderTaskForm({ taskForm });
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('Parquet Format Preview')).toBeInTheDocument();
    });

    it('renders no columns placeholder when no columns defined', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      expect(
        screen.getByText(
          'No columns defined. Add columns to describe the expected parquet structure.',
        ),
      ).toBeInTheDocument();
    });

    it('renders metrics with weight, column selector, and parameters', () => {
      const taskForm = {
        ...defaultTaskForm,
        metrics_config: JSON.stringify({
          _columns: [{ name: 'label', type: 'string', desc: 'label' }],
          accuracy: {
            weight: 1.0,
            options: { column: 'label' },
          },
        }),
      };
      const availableMetrics = {
        accuracy: {},
      };
      renderTaskForm({ taskForm, availableMetrics });
      fireEvent.click(screen.getByText('Evaluation'));

      const metricCells = screen.getAllByText('accuracy');
      expect(metricCells.length).toBeGreaterThanOrEqual(1);
      const weightInput = screen.getByDisplayValue('1');
      expect(weightInput).toBeInTheDocument();
    });

    it('renders metric param options based on availableMetrics schema', () => {
      const taskForm = {
        ...defaultTaskForm,
        metrics_config: JSON.stringify({
          _columns: [{ name: 'label', type: 'string', desc: 'label' }],
          f1_score: {
            weight: 1.0,
            options: { column: 'label', average: 'macro' },
          },
        }),
      };
      const availableMetrics = {
        f1_score: {
          average: ['micro', 'macro', 'weighted'],
        },
      };
      renderTaskForm({ taskForm, availableMetrics });
      fireEvent.click(screen.getByText('Evaluation'));

      const metricCells = screen.getAllByText('f1 score');
      expect(metricCells.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Sandbox Tab', () => {
    it('renders RAM limit input', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(screen.getByText('Override RAM Limit (MB)')).toBeInTheDocument();
    });

    it('renders Timeout limit input', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(screen.getByText('Override Timeout Limit (sec)')).toBeInTheDocument();
    });

    it('renders GPU toggle', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(screen.getByText('Requires GPU Worker Node')).toBeInTheDocument();
    });

    it('renders ban magic commands toggle', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(
        screen.getByText('Ban Jupyter magic command symbols (!) or (%) (Score 0 if found)'),
      ).toBeInTheDocument();
    });

    it('renders banned imports input', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(
        screen.getByText('Banned Libraries list (comma-separated, checked via AST imports)'),
      ).toBeInTheDocument();
    });

    it('renders whitelisted imports input', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(
        screen.getByText('Whitelisted Libraries (comma-separated, always allowed)'),
      ).toBeInTheDocument();
    });
  });

  describe('Environment Tab', () => {
    it('renders Docker base image input', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('Base Image')).toBeInTheDocument();
    });

    it('renders APT packages input', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('APT System Packages (comma-separated)')).toBeInTheDocument();
    });

    it('renders PIP requirements input', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('PIP Packages requirements.txt content')).toBeInTheDocument();
    });

    it('renders HuggingFace dataset field', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('HF Datasets (comma-separated)')).toBeInTheDocument();
    });

    it('renders HuggingFace models field', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('HF Models (comma-separated)')).toBeInTheDocument();
    });

    it('renders HuggingFace API key field', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('HF API Key Token (Securely Encrypted)')).toBeInTheDocument();
    });
  });

  describe('Files Tab', () => {
    it('renders FileUploader for labels.parquet with correct accept', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Files'));
      const uploader = screen.getByTestId('fileuploader-ground-truth-&-resources');
      expect(uploader).toBeInTheDocument();
      const acceptElements = screen.getAllByTestId('fileuploader-accept');
      expect(acceptElements[0]).toHaveTextContent('.parquet,.csv,.py,.txt,.json,.jsonl,.tsv,.pkl');
    });

    it('renders FileUploader for baseline notebook with .ipynb accept', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Files'));
      const uploader = screen.getByTestId('fileuploader-baseline-code');
      expect(uploader).toBeInTheDocument();
      const acceptElements = screen.getAllByTestId('fileuploader-accept');
      expect(acceptElements[1]).toHaveTextContent('.ipynb');
    });

    it('shows existing files from editingTask', () => {
      const editingTask = {
        id: 1,
        title: 'Edit Task',
        challenge_id: 1,
        files: [{ filename: 'labels.parquet', size_bytes: 2048 }],
        filesToDelete: [],
      };
      renderTaskForm({ editingTask, isCreatingTask: false });
      fireEvent.click(screen.getByText('Files'));
      expect(screen.getByTestId('existing-file-labels.parquet')).toBeInTheDocument();
      expect(screen.getByText('labels.parquet')).toBeInTheDocument();
    });
  });

  describe('Form Submission', () => {
    it('calls handleSaveCreateTask with correct form data on save when creating', () => {
      const handleSaveCreateTask = vi.fn((e) => e.preventDefault());
      renderTaskForm({ handleSaveCreateTask });

      const form = document.querySelector('form');
      fireEvent.submit(form);

      expect(handleSaveCreateTask).toHaveBeenCalledOnce();
    });

    it('calls handleSaveUpdateTask with correct form data on save when updating', () => {
      const handleSaveUpdateTask = vi.fn((e) => e.preventDefault());
      renderTaskForm({
        handleSaveUpdateTask,
        isCreatingTask: false,
        editingTask: { id: 1, title: 'Test', challenge_id: 1 },
      });

      const form = document.querySelector('form');
      fireEvent.submit(form);

      expect(handleSaveUpdateTask).toHaveBeenCalledOnce();
    });

    it('submit button shows loading text when saving', () => {
      renderTaskForm({ savingTask: true });
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('submit button shows create text when creating', () => {
      renderTaskForm();
      expect(screen.getByText('Create Task')).toBeInTheDocument();
    });

    it('submit button shows save text when editing', () => {
      renderTaskForm({
        isCreatingTask: false,
        editingTask: { id: 1, title: 'Test', challenge_id: 1 },
      });
      expect(screen.getByText('Save Changes')).toBeInTheDocument();
    });

    it('cancel button resets editing state', () => {
      const setIsCreatingTask = vi.fn();
      const setEditingTask = vi.fn();
      renderTaskForm({ setIsCreatingTask, setEditingTask, isCreatingTask: true });
      fireEvent.click(screen.getByText('Cancel'));
      expect(setIsCreatingTask).toHaveBeenCalledWith(false);
      expect(setEditingTask).toHaveBeenCalledWith(null);
    });
  });
});
