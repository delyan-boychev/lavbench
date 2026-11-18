import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import TaskForm from '../TaskForm';

const mockConfirm = vi.fn();
vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: vi.fn(), confirm: mockConfirm }),
}));

const mockSystemStatus = vi.fn(() => ({ data: undefined }));
vi.mock('../../../hooks/useSystemStatusQuery', () => ({
  useSystemStatusQuery: () => mockSystemStatus(),
}));

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
  evaluation_mode: 'notebook',
  folder_name: '',
  reason: '',
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
  // A stable object, as TaskManager passes from useFieldErrors
  errors: {},
};

function renderTaskForm(props = {}) {
  return render(<TaskForm {...defaultProps} {...props} />);
}

// Mock FileUploader
let mockUploaderFiles = [{ name: 'test.parquet', size: 1024 }];
vi.mock('../../ui/FileUploader', () => ({
  default: ({ label, files: _files, onChange, accept, multiple, ...rest }) => (
    <div data-testid={`fileuploader-${label?.replace(/\s+/g, '-').toLowerCase()}`}>
      <span data-testid="fileuploader-label">{label}</span>
      <span data-testid="fileuploader-accept">{accept}</span>
      <span data-testid="fileuploader-multiple">{String(!!multiple)}</span>
      <span data-testid="fileuploader-files-count">{_files?.length ?? 0}</span>
      <button data-testid="fileuploader-onchange" onClick={() => onChange(mockUploaderFiles)}>
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
  FileText: () => <span data-testid="icon-filetext" />,
  X: () => <span data-testid="icon-x" />,
  Trash2: () => <span data-testid="icon-trash2" />,
  Package: () => <span data-testid="icon-package" />,
  Zap: () => <span data-testid="icon-zap" />,
  ChevronDown: () => <span data-testid="icon-chevron-down" />,
  Check: () => <span data-testid="icon-check" />,
  AlertTriangle: () => <span data-testid="icon-alert-triangle" />,
  ArrowLeft: () => <span data-testid="icon-arrow-left" />,
}));

describe('TaskForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfirm.mockResolvedValue(true);
    mockUploaderFiles = [{ name: 'test.parquet', size: 1024 }];
    mockSystemStatus.mockReturnValue({ data: undefined });
  });

  describe('Evaluation mode', () => {
    const fileForm = { ...defaultTaskForm, evaluation_mode: 'file' };

    it('shows only the sections of the notebook mode', () => {
      renderTaskForm();
      expect(screen.getByText('Sandbox')).toBeInTheDocument();
      expect(screen.getByText('Environment')).toBeInTheDocument();
    });

    it('hides the sandbox and image tabs for a file task', () => {
      renderTaskForm({ taskForm: fileForm });
      expect(screen.queryByText('Sandbox')).not.toBeInTheDocument();
      expect(screen.queryByText('Environment')).not.toBeInTheDocument();
      fireEvent.click(screen.getByText('Files'));
      expect(screen.getByText('Starter notebook')).toBeInTheDocument();
      expect(screen.getByText('Missing baseline_submission.parquet')).toBeInTheDocument();
    });

    it('changes the mode through the select', () => {
      const setTaskForm = vi.fn();
      renderTaskForm({ setTaskForm });
      fireEvent.click(screen.getByRole('combobox', { name: /Evaluation mode/ }));
      fireEvent.click(screen.getByRole('option', { name: 'File' }));
      expect(setTaskForm).toHaveBeenCalledWith(
        expect.objectContaining({ evaluation_mode: 'file' }),
      );
    });

    it('shows a locked mode as read-only with the reason', () => {
      renderTaskForm({
        modeLocked: true,
        errors: { evaluation_mode: 'The evaluation mode cannot change.' },
      });
      expect(screen.getByRole('combobox', { name: /Evaluation mode/ })).toBeDisabled();
      expect(screen.getByText('The evaluation mode cannot change.')).toBeInTheDocument();
    });
  });

  describe('After publish', () => {
    const editingTask = {
      id: 1,
      title: 'Edit Task',
      challenge_id: 1,
      folder_name: 'edit-task',
      files: [{ filename: 'labels.parquet', size_bytes: 2048, visibility: 'hidden' }],
      filesToDelete: [],
    };

    it('fixes the folder and public files and asks the admin for a reason', () => {
      renderTaskForm({ editingTask, isCreatingTask: false, published: true, isAdmin: true });
      expect(screen.getByRole('textbox', { name: /Workspace folder/ })).toBeDisabled();
      fireEvent.click(screen.getByText('Files'));
      expect(
        screen.getByText('The workspaces are published, so these files are fixed.'),
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('fileuploader-hidden:-labels,-baseline-submission'),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('textbox', { name: /Reason for changing hidden files/ }),
      ).toBeEnabled();
    });

    it('shows the jury the reason field disabled with a hint', () => {
      renderTaskForm({ editingTask, isCreatingTask: false, published: true, isAdmin: false });
      fireEvent.click(screen.getByText('Files'));
      expect(
        screen.queryByTestId('fileuploader-hidden:-labels,-baseline-submission'),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('textbox', { name: /Reason for changing hidden files/ }),
      ).toBeDisabled();
      expect(
        screen.getAllByText(/Only an administrator can replace hidden files/).length,
      ).toBeGreaterThan(0);
    });
  });

  describe('GPU hint', () => {
    it('warns when no GPU worker is online', () => {
      mockSystemStatus.mockReturnValue({
        data: { workers: [{ online: true, queues: ['cpu_queue'] }] },
      });
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(screen.getByTestId('gpu-worker-hint')).toBeInTheDocument();
    });

    it('says nothing while the task does not ask for a GPU', () => {
      mockSystemStatus.mockReturnValue({
        data: { workers: [{ online: true, queues: ['cpu_queue'] }] },
      });
      renderTaskForm({ taskForm: { ...defaultTaskForm, gpu_required: false } });
      fireEvent.click(screen.getByText('Sandbox'));
      expect(screen.queryByTestId('gpu-worker-hint')).not.toBeInTheDocument();
    });

    it('stays quiet while a GPU worker reports in', () => {
      mockSystemStatus.mockReturnValue({
        data: { workers: [{ online: true, queues: ['gpu_queue'] }] },
      });
      renderTaskForm();
      fireEvent.click(screen.getByText('Sandbox'));
      expect(screen.queryByTestId('gpu-worker-hint')).not.toBeInTheDocument();
    });
  });

  describe('Emergency upload switch', () => {
    const fileTask = {
      id: 1,
      title: 'File task',
      challenge_id: 1,
      evaluation_mode: 'file',
      emergency_upload_enabled: false,
      files: [],
    };
    const fileForm = { ...defaultTaskForm, evaluation_mode: 'file' };

    it('is offered to the admin on a file task and reports the new value', () => {
      const onToggleEmergency = vi.fn();
      renderTaskForm({
        taskForm: fileForm,
        editingTask: fileTask,
        isCreatingTask: false,
        isAdmin: true,
        onToggleEmergency,
      });
      fireEvent.click(screen.getByLabelText('Allow the emergency upload (nanoColab outage)'));
      expect(onToggleEmergency).toHaveBeenCalledWith(true);
    });

    it('is not shown to the jury', () => {
      renderTaskForm({ taskForm: fileForm, editingTask: fileTask, isCreatingTask: false });
      expect(screen.queryByTestId('emergency-upload')).not.toBeInTheDocument();
    });
  });

  describe('General Tab (default)', () => {
    it('renders title input', () => {
      renderTaskForm();
      const titleInput = screen.getByRole('textbox', { name: /Task Title/ });
      expect(titleInput).toBeInTheDocument();
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
      expect(screen.getByRole('button', { name: /General/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      expect(screen.getByRole('button', { name: /Files/ })).toHaveAttribute(
        'aria-pressed',
        'false',
      );
    });

    it('switches to Evaluation tab when clicked', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('Column Definitions')).toBeInTheDocument();
      expect(screen.queryByLabelText('Task Title *')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Evaluation/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
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
      expect(screen.getByText('Hidden: labels, baseline submission')).toBeInTheDocument();
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

    it('shows problem codes banner when problem_codes is set', () => {
      const propsWithProblems = {
        taskForm: { ...defaultTaskForm, problem_codes: ['ERR_HF_DOWNLOAD_FAILED'] },
      };
      renderTaskForm(propsWithProblems);
      fireEvent.click(screen.getByText('Environment'));
      expect(screen.getByText('Task Problems')).toBeInTheDocument();
      expect(
        screen.getByText('Hugging Face dataset or model download failed.'),
      ).toBeInTheDocument();
    });
  });

  describe('Files Tab', () => {
    it('offers a public and a hidden drop zone', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Files'));
      expect(screen.getByTestId('fileuploader-students-get-these')).toBeInTheDocument();
      expect(
        screen.getByTestId('fileuploader-hidden:-labels,-baseline-submission'),
      ).toBeInTheDocument();
      const acceptElements = screen.getAllByTestId('fileuploader-accept');
      expect(acceptElements[0]).toHaveTextContent(
        '.parquet,.csv,.py,.txt,.json,.jsonl,.tsv,.pkl,.ipynb',
      );
      expect(acceptElements[1]).not.toHaveTextContent('.ipynb');
    });

    it('moves labels.parquet dropped among public files to the hidden list', () => {
      const setHiddenFiles = vi.fn();
      const setTaskFiles = vi.fn();
      const labels = { name: 'labels.parquet', size: 10 };
      const data = { name: 'data.csv', size: 10 };
      mockUploaderFiles = [labels, data];
      renderTaskForm({ setHiddenFiles, setTaskFiles });
      fireEvent.click(screen.getByText('Files'));
      const publicZone = screen.getByTestId('fileuploader-students-get-these');
      fireEvent.click(within(publicZone).getByTestId('fileuploader-onchange'));
      expect(setTaskFiles).toHaveBeenCalledWith([data]);
      const update = setHiddenFiles.mock.calls[0][0];
      expect(update([])).toEqual([labels]);
    });

    it('splits stored files by their visibility', () => {
      const editingTask = {
        id: 1,
        title: 'Edit Task',
        challenge_id: 1,
        files: [
          { filename: 'labels.parquet', size_bytes: 2048, visibility: 'hidden' },
          { filename: 'train.csv', size_bytes: 2048, visibility: 'public' },
        ],
        filesToDelete: [],
      };
      renderTaskForm({ editingTask, isCreatingTask: false });
      fireEvent.click(screen.getByText('Files'));
      expect(
        within(screen.getByTestId('hidden-files')).getByText('labels.parquet'),
      ).toBeInTheDocument();
      expect(within(screen.getByTestId('public-files')).getByText('train.csv')).toBeInTheDocument();
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

  describe('Evaluator Section', () => {
    it('renders custom evaluator section in Evaluation tab', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('Custom Evaluator Script')).toBeInTheDocument();
    });

    it('shows existing evaluator file when editingTask has evaluator_script_path', () => {
      const editingTask = {
        id: 1,
        title: 'Edit Eval Task',
        challenge_id: 1,
        evaluator_script_path: '/path/to/evaluator.py',
        evaluator_metric_name: 'my_metric',
      };
      renderTaskForm({ editingTask, isCreatingTask: false });
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('evaluator.py')).toBeInTheDocument();
      expect(screen.getByText('my_metric')).toBeInTheDocument();
    });

    it('shows existing evaluator without metric name when none is set', () => {
      const editingTask = {
        id: 2,
        title: 'Edit Eval No Metric',
        challenge_id: 1,
        evaluator_script_path: '/path/to/eval.py',
        evaluator_metric_name: null,
      };
      renderTaskForm({ editingTask, isCreatingTask: false });
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('evaluator.py')).toBeInTheDocument();
    });

    it('shows upload area when no evaluator exists', () => {
      renderTaskForm();
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('.py')).toBeInTheDocument();
    });

    it('existing evaluator has a remove button', () => {
      const editingTask = {
        id: 1,
        title: 'Edit Eval Task',
        challenge_id: 1,
        evaluator_script_path: '/path/to/evaluator.py',
        evaluator_metric_name: 'my_metric',
      };
      renderTaskForm({ editingTask, isCreatingTask: false });
      fireEvent.click(screen.getByText('Evaluation'));
      expect(screen.getByText('evaluator.py')).toBeInTheDocument();
      expect(screen.getByTestId('icon-x')).toBeInTheDocument();
    });
  });

  it('switches tabs when rendered without an errors prop', () => {
    const withoutErrors = { ...defaultProps };
    delete withoutErrors.errors;
    render(<TaskForm {...withoutErrors} />);
    fireEvent.click(screen.getByRole('button', { name: /Sandbox/ }));
    expect(screen.getByRole('button', { name: /Sandbox/ })).toHaveAttribute('aria-pressed', 'true');
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

    it('submit button keeps its label, busy and disabled, while saving', () => {
      renderTaskForm({ savingTask: true });
      const submit = screen.getByRole('button', { name: 'Create Task' });
      expect(submit).toHaveAttribute('aria-busy', 'true');
      expect(submit).toBeDisabled();
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
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

    it('cancel button calls onClose', async () => {
      const onClose = vi.fn();
      renderTaskForm({ onClose, isCreatingTask: true });
      fireEvent.click(screen.getByText('Cancel'));
      await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
      expect(mockConfirm).not.toHaveBeenCalled();
    });

    it('back button calls onClose', async () => {
      const onClose = vi.fn();
      renderTaskForm({ onClose });
      fireEvent.click(screen.getByRole('button', { name: /Back/ }));
      await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    });

    it('asks before closing with unsaved changes and stays open when kept', async () => {
      mockConfirm.mockResolvedValue(false);
      const onClose = vi.fn();
      renderTaskForm({ onClose, dirty: true });
      fireEvent.click(screen.getByText('Cancel'));
      await waitFor(() => expect(mockConfirm).toHaveBeenCalledOnce());
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe('Field errors', () => {
    it('shows an error message under its field', () => {
      renderTaskForm({ errors: { title: 'Title is required.' } });
      expect(screen.getByText('Title is required.')).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: /Task Title/ })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
    });

    it('opens the tab of the first error when new errors arrive', () => {
      const { rerender } = renderTaskForm();
      expect(screen.getByRole('textbox', { name: /Task Title/ })).toBeInTheDocument();
      rerender(
        <TaskForm {...defaultProps} errors={{ base_docker_image: 'Invalid image name.' }} />,
      );
      expect(screen.getByRole('button', { name: /Environment/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      expect(screen.getByText('Base Image')).toBeInTheDocument();
      expect(screen.getByText('Invalid image name.')).toBeInTheDocument();
    });

    it('opens the earliest tab when errors span several tabs', () => {
      const { rerender } = renderTaskForm();
      fireEvent.click(screen.getByText('Files'));
      rerender(
        <TaskForm
          {...defaultProps}
          errors={{ base_docker_image: 'Invalid image name.', title: 'Title is required.' }}
        />,
      );
      expect(screen.getByRole('button', { name: /General/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      expect(screen.getByText('Title is required.')).toBeInTheDocument();
    });
  });
});
