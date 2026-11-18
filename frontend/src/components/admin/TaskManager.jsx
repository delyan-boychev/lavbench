import React, { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../../context/AppContext';
import { useCreateTask, useUpdateTask } from '../../hooks/useTaskMutations';
import TaskForm from './TaskForm';
import { formatDateTime } from '../../utils/formatDate';
import { formatMetricName } from '../../utils/metrics';
import { useApiError, useApiErrorText } from '../../hooks/useApiError';
import { useFieldErrors } from '../../hooks/useFieldErrors';
import { useNotifications } from '../../context/NotificationsContext';
import { requireOk } from '../../services/apiResult';
import api from '../../services/ApiService';
import {
  BASELINE_SUBMISSION_FILE,
  LABELS_FILE,
  parseTaskFiles,
  storedVisibility,
} from '../../utils/taskFiles';

// Server refusals that name no field but belong under one
const CODE_FIELDS = {
  ERR_TASK_MODE_LOCKED: 'evaluation_mode',
  ERR_REASON_REQUIRED: 'reason',
  ERR_TASK_FOLDER_TAKEN: 'folder_name',
  ERR_TASK_FOLDER_INVALID: 'folder_name',
  ERR_ENVIRONMENT_LOCKED: 'folder_name',
  ERR_BASELINE_SUBMISSION_INVALID: 'hidden_files',
  ERR_TASK_FILES_LOCKED: 'files',
  ERR_INVALID_FILENAME: 'files',
};

export default function TaskManager({
  mode,
  initialTask,
  challenges,
  selectedChallenge,
  availableMetrics,
  onClose,
  isAdmin = false,
}) {
  const { t } = useTranslation();
  const { showToast } = useApp();
  const { confirm } = useNotifications();

  const { showApiError } = useApiError();
  const formatApiError = useApiErrorText();

  const createTaskMutation = useCreateTask();
  const updateTaskMutation = useUpdateTask();

  const isCreatingTask = mode === 'create';
  // TaskForm marks the baseline and data files to delete on this copy
  const [editingTask, setEditingTask] = useState(mode === 'edit' ? initialTask : null);

  const fieldErrors = useFieldErrors();
  const { reset: resetErrors } = fieldErrors;
  const [taskForm, setTaskFormState] = useState(
    editingTask
      ? {
          title: editingTask.title || '',
          evaluation_mode: editingTask.evaluation_mode || 'notebook',
          folder_name: editingTask.folder_name || '',
          reason: '',
          description: editingTask.description || '',
          ram_limit_mb: editingTask.ram_limit_mb !== null ? editingTask.ram_limit_mb : '',
          time_limit_sec: editingTask.time_limit_sec !== null ? editingTask.time_limit_sec : '',
          // A task without its own GPU flag inherits the challenge's, which defaults to CPU
          gpu_required: editingTask.gpu_required ?? selectedChallenge?.gpu_required ?? false,
          base_docker_image: editingTask.base_docker_image || '',
          apt_packages: editingTask.apt_packages || '',
          pip_requirements: editingTask.pip_requirements || '',
          ban_magic_commands: editingTask.ban_magic_commands || false,
          banned_imports: editingTask.banned_imports || '',
          whitelisted_imports: editingTask.whitelisted_imports || '',
          metrics_config: editingTask.metrics_config
            ? JSON.stringify(editingTask.metrics_config)
            : '',
          hf_datasets_raw: editingTask.hf_datasets
            ? Array.isArray(editingTask.hf_datasets)
              ? editingTask.hf_datasets.join(', ')
              : ''
            : '',
          hf_models_raw: editingTask.hf_models
            ? Array.isArray(editingTask.hf_models)
              ? editingTask.hf_models.join(', ')
              : ''
            : '',
          hf_api_key: '',
          public_eval_percentage: editingTask.public_eval_percentage ?? 30,
          max_submissions_per_period:
            editingTask.max_submissions_per_period !== null
              ? editingTask.max_submissions_per_period
              : '',
          submission_period_hours:
            editingTask.submission_period_hours !== null ? editingTask.submission_period_hours : '',
          stage_id:
            editingTask.stage_id !== null && editingTask.stage_id !== undefined
              ? editingTask.stage_id.toString()
              : '',
          problem_codes: editingTask.problem_codes || [],
        }
      : {
          title: '',
          evaluation_mode: 'notebook',
          folder_name: '',
          reason: '',
          description: '',
          ram_limit_mb: '',
          time_limit_sec: '',
          gpu_required: selectedChallenge?.gpu_required ?? false,
          base_docker_image: '',
          apt_packages: '',
          pip_requirements: '',
          ban_magic_commands: false,
          banned_imports: '',
          whitelisted_imports: '',
          metrics_config: '{"accuracy": {"weight": 1.0, "higher_is_better": true}}',
          hf_datasets_raw: '',
          hf_models_raw: '',
          hf_api_key: '',
          public_eval_percentage: 30,
          max_submissions_per_period: '',
          submission_period_hours: '',
          stage_id: '',
          problem_codes: [],
        },
  );

  const [initialForm] = useState(() => JSON.stringify(taskForm));
  const [taskFiles, setTaskFilesState] = useState([]);
  const [hiddenFiles, setHiddenFilesState] = useState([]);
  const [emergencyBusy, setEmergencyBusy] = useState(false);
  const [baselineFile, setBaselineFileState] = useState(null);
  const [evaluatorScript, setEvaluatorScript] = useState(null);
  const [evaluatorDeleted, setEvaluatorDeleted] = useState(false);

  // An edit clears the errors of the last save attempt
  const setTaskForm = useCallback(
    (next) => {
      setTaskFormState(next);
      resetErrors();
    },
    [resetErrors],
  );
  const setTaskFiles = useCallback(
    (next) => {
      setTaskFilesState(next);
      resetErrors();
    },
    [resetErrors],
  );
  const setHiddenFiles = useCallback(
    (next) => {
      setHiddenFilesState(next);
      resetErrors();
    },
    [resetErrors],
  );
  const setBaselineFile = useCallback(
    (next) => {
      setBaselineFileState(next);
      resetErrors();
    },
    [resetErrors],
  );

  // The server reports both locks with the task; a refusal still lands under its field
  const modeLocked = Boolean(editingTask?.mode_locked);
  const published = Boolean(editingTask?.files_locked);
  const storedFiles = parseTaskFiles(editingTask?.files);
  const deletedNames = editingTask?.filesToDelete || [];
  const keptHidden = storedFiles
    .filter((f) => storedVisibility(f) === 'hidden' && !deletedNames.includes(f.filename))
    .map((f) => f.filename);
  const hiddenNames = [...keptHidden, ...hiddenFiles.map((f) => f.name)];
  // Hidden files and the evaluator are what an admin may still fix after publish, with a reason
  const hiddenChanges =
    hiddenFiles.length > 0 ||
    storedFiles.some(
      (f) => storedVisibility(f) === 'hidden' && deletedNames.includes(f.filename),
    ) ||
    Boolean(evaluatorScript) ||
    (evaluatorDeleted && Boolean(editingTask?.evaluator_script_path));
  const needsReason = published && hiddenChanges;
  const fileMode = taskForm.evaluation_mode === 'file';

  const dirty =
    JSON.stringify(taskForm) !== initialForm ||
    taskFiles.length > 0 ||
    hiddenFiles.length > 0 ||
    Boolean(baselineFile) ||
    Boolean(evaluatorScript) ||
    evaluatorDeleted ||
    Boolean(editingTask?.baselineDeleted) ||
    (editingTask?.filesToDelete?.length ?? 0) > 0;

  /** Per-field messages for the checks the browser cannot make. */
  const validateTaskForm = () => {
    const errors = /** @type {Record<string, string>} */ ({});
    if (!taskForm.title.trim()) errors.title = t('common.required_field_input');
    if (!hiddenNames.includes(LABELS_FILE)) {
      errors.hidden_files = t('admin.tasks.labels_parquet_required');
    } else if (fileMode && !hiddenNames.includes(BASELINE_SUBMISSION_FILE)) {
      errors.hidden_files = t('admin.tasks.baseline_submission_required');
    }
    if (needsReason && isAdmin && !taskForm.reason.trim()) {
      errors.reason = t('admin.tasks.hidden_reason_required');
    }
    // File tasks show no sandbox or image fields, so nothing there can be fixed
    if (fileMode) return errors;

    const DOCKER_IMAGE_RE =
      /^[a-z0-9]+(?:[._-][a-z0-9]+)*\/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$/;
    const APT_PACKAGE_RE = /^[a-zA-Z0-9.+-]+$/;
    const PIP_REQUIREMENT_RE =
      /^\s*([a-zA-Z0-9_.-]+)\s*(([><=!~]+)\s*[\w.*-]+(?:\s*,\s*[><=!~]+\s*[\w.*-]+)*)?\s*(#.*)?$/;

    if (taskForm.base_docker_image && !DOCKER_IMAGE_RE.test(taskForm.base_docker_image)) {
      errors.base_docker_image = t('admin.tasks.validation_invalid_docker_image');
    }

    if (taskForm.apt_packages) {
      const packages = taskForm.apt_packages
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      const invalid = packages.filter((p) => !APT_PACKAGE_RE.test(p));
      if (invalid.length > 0) {
        errors.apt_packages = t('admin.tasks.validation_invalid_apt', {
          packages: invalid.join(', '),
        });
      }
    }

    if (taskForm.pip_requirements) {
      const lines = taskForm.pip_requirements
        .split('\n')
        .filter((l) => l.trim() && !l.trim().startsWith('#'));
      const invalid = lines.filter((l) => !PIP_REQUIREMENT_RE.test(l.trim()));
      if (invalid.length > 0) {
        errors.pip_requirements = t('admin.tasks.validation_invalid_pip', {
          requirements: invalid.join('; '),
        });
      }
    }

    if (taskForm.hf_datasets_raw) {
      const count = taskForm.hf_datasets_raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean).length;
      if (count > 5) {
        errors.hf_datasets = t('admin.tasks.validation_too_many_hf_datasets', { max: 5, count });
      }
    }

    if (taskForm.hf_models_raw) {
      const count = taskForm.hf_models_raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean).length;
      if (count > 5) {
        errors.hf_models = t('admin.tasks.validation_too_many_hf_models', { max: 5, count });
      }
    }

    return errors;
  };

  const prepareTaskFormData = () => {
    const formData = new FormData();
    formData.append('title', taskForm.title);
    formData.append('evaluation_mode', taskForm.evaluation_mode);
    // An unchanged folder keeps following the title; an emptied one goes back to it
    if (
      editingTask ? taskForm.folder_name !== (editingTask.folder_name || '') : taskForm.folder_name
    )
      formData.append('folder_name', taskForm.folder_name.trim());
    if (needsReason && taskForm.reason.trim()) formData.append('reason', taskForm.reason.trim());
    formData.append('description', taskForm.description);

    if (taskForm.ram_limit_mb) formData.append('ram_limit_mb', taskForm.ram_limit_mb);
    if (taskForm.time_limit_sec) formData.append('time_limit_sec', String(taskForm.time_limit_sec));
    formData.append('gpu_required', String(taskForm.gpu_required));

    formData.append('base_docker_image', taskForm.base_docker_image);
    formData.append('apt_packages', taskForm.apt_packages);
    formData.append('pip_requirements', taskForm.pip_requirements);

    formData.append('ban_magic_commands', String(taskForm.ban_magic_commands));
    formData.append('banned_imports', taskForm.banned_imports);
    let cleanMetricsConfig = taskForm.metrics_config;
    try {
      const parsed = JSON.parse(taskForm.metrics_config);
      if (parsed && typeof parsed === 'object') {
        Object.keys(parsed).forEach((k) => {
          if (parsed[k] && parsed[k].options_raw !== undefined) {
            delete parsed[k].options_raw;
          }
        });
        cleanMetricsConfig = JSON.stringify(parsed);
      }
    } catch {
      /* noop */
    }
    formData.append('metrics_config', cleanMetricsConfig);

    if (taskForm.hf_api_key) formData.append('hf_api_key', taskForm.hf_api_key);
    formData.append('public_eval_percentage', String(taskForm.public_eval_percentage));

    formData.append('whitelisted_imports', taskForm.whitelisted_imports);
    const datasetsArray = taskForm.hf_datasets_raw
      ? taskForm.hf_datasets_raw
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
    formData.append('hf_datasets', JSON.stringify(datasetsArray));

    const modelsArray = taskForm.hf_models_raw
      ? taskForm.hf_models_raw
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
    formData.append('hf_models', JSON.stringify(modelsArray));

    if (taskForm.max_submissions_per_period)
      formData.append('max_submissions_per_period', taskForm.max_submissions_per_period);
    if (taskForm.submission_period_hours)
      formData.append('submission_period_hours', taskForm.submission_period_hours);
    if (taskForm.stage_id !== undefined && taskForm.stage_id !== null)
      formData.append('stage_id', taskForm.stage_id);

    taskFiles.forEach((file, idx) => {
      formData.append(`file_${idx}`, file);
    });
    hiddenFiles.forEach((file, idx) => {
      formData.append(`hidden_file_${idx}`, file);
    });

    if (baselineFile) formData.append('baseline_notebook', baselineFile);
    if (evaluatorScript) {
      formData.append('evaluator_script', evaluatorScript);
    } else if (evaluatorDeleted) {
      formData.append('delete_evaluator', 'true');
    }

    return formData;
  };

  /** Put a refusal under its field; false when it belongs to none. */
  const showFieldError = (data) => {
    if (fieldErrors.capture(data)) return true;
    const field = CODE_FIELDS[data?.code];
    if (!field) return false;
    fieldErrors.setErrors({ [field]: formatApiError(data) });
    return true;
  };

  /** The admin's outage switch: applied at once, with a reason to turn it on. */
  const handleToggleEmergency = async (enabled) => {
    const reason = enabled
      ? await confirm({
          title: t('admin.tasks.emergency.on_title'),
          message: t('admin.tasks.emergency.on_message'),
          confirmText: t('admin.tasks.emergency.on_confirm'),
          isPrompt: true,
          placeholder: t('admin.tasks.emergency.reason_placeholder'),
        })
      : (await confirm({
            title: t('admin.tasks.emergency.off_title'),
            message: t('admin.tasks.emergency.off_message'),
            confirmText: t('admin.tasks.emergency.off_confirm'),
          }))
        ? ''
        : null;
    if (reason === null) return;
    setEmergencyBusy(true);
    try {
      const res = requireOk(
        await api.put(`/tasks/${editingTask.id}/emergency-upload`, {
          enabled,
          reason: reason.trim(),
        }),
      );
      setEditingTask((prev) => ({
        ...prev,
        emergency_upload_enabled: Boolean(res.data?.emergency_upload_enabled),
      }));
      showToast(t(enabled ? 'admin.tasks.emergency.on_done' : 'admin.tasks.emergency.off_done'));
    } catch (error) {
      showApiError(error, 'admin.tasks.emergency.failed');
    } finally {
      setEmergencyBusy(false);
    }
  };

  const handleSaveCreateTask = async (e) => {
    e.preventDefault();
    if (!selectedChallenge) return;

    const validationErrors = validateTaskForm();
    if (!fileMode && !baselineFile) validationErrors.baseline = t('admin.tasks.baseline_required');
    if (Object.keys(validationErrors).length > 0) {
      fieldErrors.setErrors(validationErrors);
      return;
    }

    const formData = prepareTaskFormData();

    try {
      const result = await createTaskMutation.mutateAsync({
        challengeId: selectedChallenge.id,
        formData,
      });
      if (result.ok) {
        showToast(t('admin.notifications.task_created'));
        onClose && onClose();
      } else if (!showFieldError(result.data)) {
        showApiError(result.data, 'admin.notifications.task_create_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error_create_task'), 'rose');
    }
  };

  const handleSaveUpdateTask = async (e) => {
    e.preventDefault();
    if (!editingTask) return;

    const validationErrors = validateTaskForm();

    const hasBaseline =
      (editingTask.baseline_notebook_path && !editingTask.baselineDeleted) || baselineFile;
    if (!fileMode && !hasBaseline) validationErrors.baseline = t('admin.tasks.baseline_required');
    if (Object.keys(validationErrors).length > 0) {
      fieldErrors.setErrors(validationErrors);
      return;
    }

    const formData = prepareTaskFormData();
    if (deletedNames.length > 0) {
      formData.append('deleted_files', JSON.stringify(deletedNames));
    }
    if (editingTask.baselineDeleted && !baselineFile) {
      formData.append('delete_baseline', 'true');
    }

    try {
      const result = await updateTaskMutation.mutateAsync({
        taskId: editingTask.id,
        formData,
      });
      if (result.ok) {
        showToast(t('admin.notifications.task_updated'));
        onClose && onClose();
      } else if (!showFieldError(result.data)) {
        showApiError(result.data, 'admin.notifications.task_update_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error_update_task'), 'rose');
    }
  };

  return (
    <TaskForm
      taskForm={taskForm}
      setTaskForm={setTaskForm}
      isCreatingTask={isCreatingTask}
      editingTask={editingTask}
      setEditingTask={setEditingTask}
      onClose={onClose}
      handleSaveCreateTask={handleSaveCreateTask}
      handleSaveUpdateTask={handleSaveUpdateTask}
      challenges={challenges}
      selectedChallenge={selectedChallenge}
      availableMetrics={availableMetrics}
      formatMetricName={formatMetricName}
      taskFiles={taskFiles}
      setTaskFiles={setTaskFiles}
      baselineFile={baselineFile}
      setBaselineFile={setBaselineFile}
      formatDateTime={formatDateTime}
      savingTask={createTaskMutation.isPending || updateTaskMutation.isPending}
      evaluatorScript={evaluatorScript}
      setEvaluatorScript={setEvaluatorScript}
      evaluatorDeleted={evaluatorDeleted}
      setEvaluatorDeleted={setEvaluatorDeleted}
      errors={fieldErrors.errors}
      dirty={dirty}
      hiddenFiles={hiddenFiles}
      setHiddenFiles={setHiddenFiles}
      isAdmin={isAdmin}
      published={published}
      modeLocked={modeLocked}
      needsReason={needsReason}
      onToggleEmergency={handleToggleEmergency}
      emergencyBusy={emergencyBusy}
    />
  );
}

export { formatMetricName };
