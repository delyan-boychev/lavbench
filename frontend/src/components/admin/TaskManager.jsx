import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../../context/AppContext';
import { useCreateTask, useUpdateTask } from '../../hooks/useTaskMutations';
import TaskForm from './TaskForm';
import { formatDateTime } from '../../utils/formatDate';
import { formatMetricName } from '../../utils/metrics';

export default function TaskManager({
  mode,
  initialTask,
  challenges,
  selectedChallenge,
  availableMetrics,
  onClose,
}) {
  const { t } = useTranslation();
  const { showToast } = useApp();

  const showApiError = (data, defaultTranslationKey, defaultText = '') => {
    if (data?.code) {
      showToast(t(`api.${data.code}`, data.error || t(defaultTranslationKey, defaultText)), 'rose');
    } else {
      showToast(data?.error || t(defaultTranslationKey, defaultText), 'rose');
    }
  };

  const createTaskMutation = useCreateTask();
  const updateTaskMutation = useUpdateTask();

  const isCreatingTask = mode === 'create';
  const editingTask = mode === 'edit' ? initialTask : null;

  const [taskForm, setTaskForm] = useState(
    editingTask
      ? {
          title: editingTask.title || '',
          description: editingTask.description || '',
          ram_limit_mb: editingTask.ram_limit_mb !== null ? editingTask.ram_limit_mb : '',
          time_limit_sec: editingTask.time_limit_sec !== null ? editingTask.time_limit_sec : '',
          gpu_required: editingTask.gpu_required !== null ? editingTask.gpu_required : true,
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
          public_eval_percentage: editingTask.public_eval_percentage || 30,
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
        }
      : {
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
          metrics_config: '{"accuracy": {"weight": 1.0, "higher_is_better": true}}',
          hf_datasets_raw: '',
          hf_models_raw: '',
          hf_api_key: '',
          public_eval_percentage: 30,
          max_submissions_per_period: '',
          submission_period_hours: '',
          stage_id: '',
        },
  );

  const [taskFiles, setTaskFiles] = useState([]);
  const [baselineFile, setBaselineFile] = useState(null);
  const [evaluatorScript, setEvaluatorScript] = useState(null);
  const [evaluatorDeleted, setEvaluatorDeleted] = useState(false);

  const validateTaskForm = () => {
    const errors = [];

    const DOCKER_IMAGE_RE =
      /^[a-z0-9]+(?:[._-][a-z0-9]+)*\/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$/;
    const APT_PACKAGE_RE = /^[a-zA-Z0-9.+-]+$/;
    const PIP_REQUIREMENT_RE =
      /^\s*([a-zA-Z0-9_.-]+)\s*(([><=!~]+)\s*[\w.*-]+(?:\s*,\s*[><=!~]+\s*[\w.*-]+)*)?\s*(#.*)?$/;

    if (taskForm.base_docker_image && !DOCKER_IMAGE_RE.test(taskForm.base_docker_image)) {
      errors.push('Invalid Docker image format.');
    }

    if (taskForm.apt_packages) {
      const packages = taskForm.apt_packages
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      const invalid = packages.filter((p) => !APT_PACKAGE_RE.test(p));
      if (invalid.length > 0) {
        errors.push(`Invalid APT package(s): ${invalid.join(', ')}`);
      }
    }

    if (taskForm.pip_requirements) {
      const lines = taskForm.pip_requirements
        .split('\n')
        .filter((l) => l.trim() && !l.trim().startsWith('#'));
      const invalid = lines.filter((l) => !PIP_REQUIREMENT_RE.test(l.trim()));
      if (invalid.length > 0) {
        errors.push(`Invalid pip requirement(s): ${invalid.join('; ')}`);
      }
    }

    if (taskForm.hf_datasets_raw) {
      const count = taskForm.hf_datasets_raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean).length;
      if (count > 5) errors.push(`HF datasets: maximum 5 allowed, got ${count}.`);
    }

    if (taskForm.hf_models_raw) {
      const count = taskForm.hf_models_raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean).length;
      if (count > 5) errors.push(`HF models: maximum 5 allowed, got ${count}.`);
    }

    return errors;
  };

  const prepareTaskFormData = () => {
    const formData = new FormData();
    formData.append('title', taskForm.title);
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

    if (baselineFile) formData.append('baseline_notebook', baselineFile);
    if (evaluatorScript) {
      formData.append('evaluator_script', evaluatorScript);
    } else if (evaluatorDeleted) {
      formData.append('delete_evaluator', 'true');
    }

    return formData;
  };

  const handleSaveCreateTask = async (e) => {
    e.preventDefault();
    if (!selectedChallenge) return;

    const validationErrors = validateTaskForm();
    if (validationErrors.length > 0) {
      showToast(validationErrors.join('\n'), 'rose');
      return;
    }

    const hasLabels = taskFiles.some((f) => f.name === 'labels.parquet');
    if (!hasLabels) {
      showToast(t('admin.tasks.labels_parquet_required'), 'rose');
      return;
    }

    if (!baselineFile) {
      showToast(t('admin.tasks.baseline_required', 'Baseline notebook is required.'), 'rose');
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
      } else {
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
    if (validationErrors.length > 0) {
      showToast(validationErrors.join('\n'), 'rose');
      return;
    }

    const deletedNames = editingTask.filesToDelete || [];
    const existingLabels = (() => {
      if (!editingTask.files) return false;
      const filesArr = Array.isArray(editingTask.files)
        ? editingTask.files
        : typeof editingTask.files === 'string' && editingTask.files.trim() !== ''
          ? JSON.parse(editingTask.files)
          : [];
      return filesArr.some(
        (f) => f.filename === 'labels.parquet' && !deletedNames.includes(f.filename),
      );
    })();
    const newLabels = taskFiles.some((f) => f.name === 'labels.parquet');
    if (!existingLabels && !newLabels) {
      showToast(t('admin.tasks.labels_parquet_required'), 'rose');
      return;
    }

    const hasBaseline =
      (editingTask.baseline_notebook_path && !editingTask.baselineDeleted) || baselineFile;
    if (!hasBaseline) {
      showToast(t('admin.tasks.baseline_required', 'Baseline notebook is required.'), 'rose');
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
      } else {
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
      setEditingTask={() => {}}
      setIsCreatingTask={() => {}}
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
    />
  );
}

export { formatMetricName };
