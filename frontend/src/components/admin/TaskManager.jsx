import React, { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../../context/AppContext';
import {
  useCreateTask,
  useInvalidateTaskData,
  useSetEmergencyUpload,
  useUpdateTask,
} from '../../hooks/useTaskMutations';
import { useUploadQueue } from '../../hooks/useUploadQueue';
import TaskService from '../../services/TaskService';
import TaskForm from './TaskForm';
import { formatDateTime } from '../../utils/formatDate';
import { formatMetricName } from '../../utils/metrics';
import { useApiError, useApiErrorText } from '../../hooks/useApiError';
import { useFieldErrors } from '../../hooks/useFieldErrors';
import { useNotifications } from '../../context/NotificationsContext';
import { LABELS_FILE, parseTaskFiles, storedVisibility } from '../../utils/taskFiles';

// Server refusals that name no field but belong under one
const CODE_FIELDS = {
  ERR_TASK_MODE_LOCKED: 'evaluation_mode',
  ERR_REASON_REQUIRED: 'reason',
  ERR_TASK_FOLDER_TAKEN: 'folder_name',
  ERR_TASK_FOLDER_INVALID: 'folder_name',
  ERR_ENVIRONMENT_LOCKED: 'folder_name',
  ERR_TASK_FILES_LOCKED: 'files',
  ERR_INVALID_FILENAME: 'files',
};
// Form fields the server names that this form shows under another key
const FIELD_KEYS = { baseline_notebook: 'baseline' };

/** The form fields of a stored task. */
function formOfTask(task, selectedChallenge) {
  return {
    title: task.title || '',
    evaluation_mode: task.evaluation_mode || 'notebook',
    folder_name: task.folder_name || '',
    reason: '',
    description: task.description || '',
    ram_limit_mb: task.ram_limit_mb != null ? task.ram_limit_mb : '',
    time_limit_sec: task.time_limit_sec != null ? task.time_limit_sec : '',
    // A task without its own GPU flag inherits the challenge's, which defaults to CPU
    gpu_required: task.gpu_required ?? selectedChallenge?.gpu_required ?? false,
    base_docker_image: task.base_docker_image || '',
    apt_packages: task.apt_packages || '',
    pip_requirements: task.pip_requirements || '',
    ban_magic_commands: task.ban_magic_commands || false,
    banned_imports: task.banned_imports || '',
    whitelisted_imports: task.whitelisted_imports || '',
    metrics_config: task.metrics_config ? JSON.stringify(task.metrics_config) : '',
    public_eval_percentage: task.public_eval_percentage ?? 30,
    max_submissions_per_period:
      task.max_submissions_per_period != null ? task.max_submissions_per_period : '',
    submission_period_hours:
      task.submission_period_hours != null ? task.submission_period_hours : '',
    stage_id: task.stage_id != null ? task.stage_id.toString() : '',
    problem_codes: task.problem_codes || [],
  };
}

/** The form fields of a new task. */
function emptyForm(selectedChallenge) {
  return {
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
    public_eval_percentage: 30,
    max_submissions_per_period: '',
    submission_period_hours: '',
    stage_id: '',
    problem_codes: [],
  };
}

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
  const emergencyMutation = useSetEmergencyUpload();
  const invalidateTaskData = useInvalidateTaskData();

  // After a create the form shows the saved task, so a second Save cannot duplicate it
  const [isCreatingTask, setIsCreatingTask] = useState(mode === 'create');
  // TaskForm marks the baseline and data files to delete on this copy
  const [editingTask, setEditingTask] = useState(mode === 'edit' ? initialTask : null);

  // Each finished upload answers with the task, so the form lists the file as stored
  const uploads = useUploadQueue({
    onItemDone: (data) => {
      if (data && typeof data === 'object') {
        setEditingTask((prev) => ({
          ...data,
          filesToDelete: prev?.filesToDelete,
          baselineDeleted: prev?.baselineDeleted,
        }));
      }
      invalidateTaskData();
    },
  });

  const fieldErrors = useFieldErrors();
  const { reset: resetErrors } = fieldErrors;
  const [taskForm, setTaskFormState] = useState(() =>
    editingTask ? formOfTask(editingTask, selectedChallenge) : emptyForm(selectedChallenge),
  );

  const [initialForm, setInitialForm] = useState(() => JSON.stringify(taskForm));
  const [taskFiles, setTaskFilesState] = useState([]);
  const [hiddenFiles, setHiddenFilesState] = useState([]);
  const [emergencyBusy, setEmergencyBusy] = useState(false);
  const [baselineFile, setBaselineFileState] = useState(null);
  const [evaluatorScript, setEvaluatorScript] = useState(null);
  const [evaluatorDeleted, setEvaluatorDeleted] = useState(false);
  const [hfZipFile, setHfZipFileState] = useState(/** @type {File | null} */ (null));
  const [hfZipDeleted, setHfZipDeleted] = useState(false);
  // Counts the user's edits, so a save that finishes later keeps newer edits on screen
  const edits = useRef(0);
  /** Wrap a setter TaskForm calls, so its changes count as edits. */
  const counted = (setter) => (next) => {
    edits.current += 1;
    setter(next);
  };

  // An edit clears the errors of the last save attempt
  const setTaskForm = useCallback(
    (next) => {
      edits.current += 1;
      setTaskFormState(next);
      resetErrors();
    },
    [resetErrors],
  );
  const setTaskFiles = useCallback(
    (next) => {
      edits.current += 1;
      setTaskFilesState(next);
      resetErrors();
    },
    [resetErrors],
  );
  const setHiddenFiles = useCallback(
    (next) => {
      edits.current += 1;
      setHiddenFilesState(next);
      resetErrors();
    },
    [resetErrors],
  );
  const setBaselineFile = useCallback(
    (next) => {
      edits.current += 1;
      setBaselineFileState(next);
      resetErrors();
    },
    [resetErrors],
  );
  const setHfZipFile = useCallback(
    (next) => {
      edits.current += 1;
      setHfZipFileState(next);
      resetErrors();
    },
    [resetErrors],
  );

  // The server reports both locks with the task; a refusal still lands under its field
  const modeLocked = Boolean(editingTask?.mode_locked);
  const published = Boolean(editingTask?.files_locked);
  const storedFiles = parseTaskFiles(editingTask?.files);
  const deletedNames = editingTask?.filesToDelete || [];
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
  // A picked ZIP replaces the stored one, so the removal is only sent without one
  const removeHfZip = hfZipDeleted && !hfZipFile;
  const initialStage = editingTask?.stage_id != null ? String(editingTask.stage_id) : '';

  /** The fields this form shows an error under in its current state. */
  const shownFields = () => {
    const fields = new Set(['title', 'folder_name', 'evaluation_mode', 'stage_id']);
    if (!fileMode) {
      ['base_docker_image', 'apt_packages', 'pip_requirements'].forEach((field) =>
        fields.add(field),
      );
    }
    if (!published) ['files', 'baseline'].forEach((field) => fields.add(field));
    if (!published || isAdmin) fields.add('hidden_files');
    if (published) fields.add('reason');
    return fields;
  };

  /** Show checks under their fields; a message whose field is not on screen becomes a toast. */
  const showErrors = (errors) => {
    const shown = shownFields();
    const onScreen = Object.fromEntries(Object.entries(errors).filter(([key]) => shown.has(key)));
    Object.entries(errors)
      .filter(([key]) => !shown.has(key))
      .forEach(([, message]) => showToast(message, 'rose'));
    fieldErrors.setErrors(onScreen);
  };

  // What the task request itself sends; data files and the HF ZIP stream after it
  const formDirty =
    JSON.stringify(taskForm) !== initialForm ||
    Boolean(baselineFile) ||
    Boolean(evaluatorScript) ||
    evaluatorDeleted ||
    Boolean(editingTask?.baselineDeleted);
  const dirty =
    formDirty ||
    taskFiles.length > 0 ||
    hiddenFiles.length > 0 ||
    Boolean(hfZipFile) ||
    removeHfZip ||
    deletedNames.length > 0;

  /** Per-field messages for the checks the browser cannot make. */
  const validateTaskForm = () => {
    const errors = /** @type {Record<string, string>} */ ({});
    if (!taskForm.title.trim()) errors.title = t('common.required_field_input');
    // A missing labels file shows as a readiness problem of the saved task, not here
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

    // A file task runs no code, so its hidden sandbox fields are never sent or checked
    if (!fileMode) {
      if (taskForm.ram_limit_mb) formData.append('ram_limit_mb', taskForm.ram_limit_mb);
      if (taskForm.time_limit_sec)
        formData.append('time_limit_sec', String(taskForm.time_limit_sec));
      formData.append('gpu_required', String(taskForm.gpu_required));
      formData.append('base_docker_image', taskForm.base_docker_image);
      formData.append('apt_packages', taskForm.apt_packages);
      formData.append('pip_requirements', taskForm.pip_requirements);
      formData.append('ban_magic_commands', String(taskForm.ban_magic_commands));
      formData.append('banned_imports', taskForm.banned_imports);
    }
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

    formData.append('public_eval_percentage', String(taskForm.public_eval_percentage));

    if (!fileMode) formData.append('whitelisted_imports', taskForm.whitelisted_imports);

    if (taskForm.max_submissions_per_period)
      formData.append('max_submissions_per_period', taskForm.max_submissions_per_period);
    if (taskForm.submission_period_hours)
      formData.append('submission_period_hours', taskForm.submission_period_hours);
    if (taskForm.stage_id !== undefined && taskForm.stage_id !== null)
      formData.append('stage_id', taskForm.stage_id);

    if (baselineFile) formData.append('baseline_notebook', baselineFile);
    if (evaluatorScript) {
      formData.append('evaluator_script', evaluatorScript);
    } else if (evaluatorDeleted) {
      formData.append('delete_evaluator', 'true');
    }

    return formData;
  };

  /** Put a refusal under its field; false when that field is not on screen, so a toast shows it. */
  const showFieldError = (data) => {
    const body = data?.data && typeof data.data === 'object' ? data.data : data;
    // Labels errors name the file, which this form shows in the hidden-files zone
    const named = typeof body?.field === 'string' ? FIELD_KEYS[body.field] || body.field : '';
    let field = CODE_FIELDS[body?.code] || named;
    if (body?.code === 'ERR_TASK_FILES_LOCKED' && taskForm.stage_id !== initialStage) {
      field = 'stage_id';
    }
    if (!field || !shownFields().has(field)) return false;
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
    if (enabled && !reason.trim()) {
      showToast(t('admin.tasks.emergency.reason_required'), 'rose');
      return;
    }
    setEmergencyBusy(true);
    try {
      const res = await emergencyMutation.mutateAsync({
        taskId: editingTask.id,
        enabled,
        reason: reason.trim(),
      });
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

  /** Show the saved task as the form's new starting point, with nothing left to send. */
  const adoptSavedTask = (saved) => {
    const form = formOfTask(saved, selectedChallenge);
    setIsCreatingTask(false);
    // The marks for deletion were sent; the copy starts clean
    setEditingTask({ ...saved, filesToDelete: [], baselineDeleted: false });
    setTaskFormState(form);
    setInitialForm(JSON.stringify(form));
    setTaskFilesState([]);
    setHiddenFilesState([]);
    setBaselineFileState(null);
    setEvaluatorScript(null);
    setEvaluatorDeleted(false);
    setHfZipFileState(null);
    setHfZipDeleted(false);
  };

  /** The removals marked on a stored task, sent before the uploads. */
  const removalEntries = (taskId, reason) => [
    ...deletedNames.map((filename) => {
      const hidden = storedFiles.some(
        (f) => f.filename === filename && storedVisibility(f) === 'hidden',
      );
      return {
        remove: true,
        name: filename,
        path: TaskService.filePath(taskId, filename, { reason: hidden ? reason : '' }),
      };
    }),
    ...(removeHfZip
      ? [{ remove: true, name: t('admin.tasks.hf.title'), path: TaskService.hfZipPath(taskId) }]
      : []),
  ];

  /** The picked data files and HF ZIP of a saved task, in the order they upload. */
  const uploadEntries = (taskId, reason) => [
    ...taskFiles.map((file) => ({
      file,
      path: TaskService.filePath(taskId, file.name, { visibility: 'public' }),
    })),
    // The server checks baseline_submission.parquet against the labels, so labels go first
    ...[...hiddenFiles]
      .sort((a, b) => Number(b.name === LABELS_FILE) - Number(a.name === LABELS_FILE))
      .map((file) => ({
        file,
        path: TaskService.filePath(taskId, file.name, { visibility: 'hidden', reason }),
      })),
    ...(hfZipFile
      ? [{ file: hfZipFile, path: TaskService.hfZipPath(taskId), contentType: 'application/zip' }]
      : []),
  ];

  /** Send the removals and stream the picked files after a save, then close when all are done. */
  const finishSave = async (saved, entries, doneKey) => {
    adoptSavedTask(saved);
    const editsAtSave = edits.current;
    const allDone = await uploads.enqueue(entries);
    if (!allDone) {
      showToast(t('upload_list.saved_with_failures'), 'rose');
      return;
    }
    showToast(t(doneKey));
    if (edits.current === editsAtSave) onClose && onClose();
  };

  /** Closing while files upload asks first, then cancels them. */
  const handleClose = async () => {
    if (uploads.running) {
      const ok = await confirm({
        title: t('upload_list.close_title'),
        message: t('upload_list.close_message'),
        confirmText: t('upload_list.close_confirm'),
        cancelText: t('upload_list.keep_uploading'),
      });
      if (!ok) return;
      uploads.cancelAll();
    }
    onClose && onClose();
  };

  const handleSaveCreateTask = async (e) => {
    e.preventDefault();
    if (!selectedChallenge) return;

    const validationErrors = validateTaskForm();
    if (!fileMode && !baselineFile) validationErrors.baseline = t('admin.tasks.baseline_required');
    if (Object.keys(validationErrors).length > 0) {
      showErrors(validationErrors);
      return;
    }

    const formData = prepareTaskFormData();

    let result;
    try {
      result = await createTaskMutation.mutateAsync({
        challengeId: selectedChallenge.id,
        formData,
      });
    } catch {
      showToast(t('admin.notifications.network_error_create_task'), 'rose');
      return;
    }
    if (!result.ok) {
      if (!showFieldError(result.data)) {
        showApiError(result.data, 'admin.notifications.task_create_failed');
      }
      return;
    }
    await finishSave(
      result.data,
      uploadEntries(result.data.id, ''),
      'admin.notifications.task_created',
    );
  };

  const handleSaveUpdateTask = async (e) => {
    e.preventDefault();
    if (!editingTask) return;

    const validationErrors = validateTaskForm();

    const hasBaseline =
      (editingTask.baseline_notebook_path && !editingTask.baselineDeleted) || baselineFile;
    if (!fileMode && !hasBaseline) validationErrors.baseline = t('admin.tasks.baseline_required');
    if (Object.keys(validationErrors).length > 0) {
      showErrors(validationErrors);
      return;
    }

    const formData = prepareTaskFormData();
    if (editingTask.baselineDeleted && !baselineFile) {
      formData.append('delete_baseline', 'true');
    }

    let result;
    try {
      result = await updateTaskMutation.mutateAsync({
        taskId: editingTask.id,
        formData,
      });
    } catch {
      showToast(t('admin.notifications.network_error_update_task'), 'rose');
      return;
    }
    if (!result.ok) {
      if (!showFieldError(result.data)) {
        showApiError(result.data, 'admin.notifications.task_update_failed');
      }
      return;
    }
    // An admin's reason covers every hidden file changed after publish
    const reason = needsReason && isAdmin ? taskForm.reason.trim() : '';
    const entries = [
      ...removalEntries(editingTask.id, reason),
      ...uploadEntries(editingTask.id, reason),
    ];
    await finishSave(
      { ...editingTask, ...result.data },
      entries,
      'admin.notifications.task_updated',
    );
  };

  return (
    <TaskForm
      taskForm={taskForm}
      setTaskForm={setTaskForm}
      isCreatingTask={isCreatingTask}
      editingTask={editingTask}
      setEditingTask={counted(setEditingTask)}
      onClose={handleClose}
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
      savingTask={createTaskMutation.isPending || updateTaskMutation.isPending || uploads.running}
      evaluatorScript={evaluatorScript}
      setEvaluatorScript={counted(setEvaluatorScript)}
      evaluatorDeleted={evaluatorDeleted}
      setEvaluatorDeleted={counted(setEvaluatorDeleted)}
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
      hfZipFile={hfZipFile}
      setHfZipFile={setHfZipFile}
      hfZipDeleted={hfZipDeleted}
      onToggleHfZipDeleted={counted(() => setHfZipDeleted((prev) => !prev))}
      uploadItems={uploads.items}
      onCancelUpload={uploads.cancel}
      onRetryUpload={uploads.retry}
    />
  );
}

export { formatMetricName };
