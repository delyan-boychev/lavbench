import React, { useState, useRef } from 'react';
import api from '../../services/ApiService';
import ChallengeService from '../../services/ChallengeService';
import { useTranslation } from 'react-i18next';
import { useApp } from '../../context/AppContext';
import { useAuth } from '../../AuthContext';
import {
  useUpdateChallenge,
  useDeleteChallenge,
  useFinalizeChallenge,
  useToggleRevealChallenge,
  useArchiveToggle,
  useExportChallenge,
  useImportChallenge,
} from '../../hooks/useChallengeMutations';
import {
  useCreateStage,
  useUpdateStage,
  useDeleteStage,
  useFinalizeStage,
  useToggleRevealStage,
} from '../../hooks/useStageMutations';
import { useDeleteTask } from '../../hooks/useTaskMutations';
import { useAdminChallengesQuery } from '../../hooks/useAdminChallengesQuery';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import FormView from '../ui/FormView';
import InputField from '../ui/InputField';
import Pagination from '../ui/Pagination';
import Notice from '../ui/Notice';
import { Plus, AlertTriangle } from 'lucide-react';
import CompetitionFields from './CompetitionFields';
import FinalizeDialog from './FinalizeDialog';
import WorkspaceSettingsSection from './WorkspaceSettingsSection';
import WorkspacesPanel from './WorkspacesPanel';
import {
  useEnvironmentsQuery,
  useWorkspaceCatalogQuery,
  workspacesOffered,
} from '../../hooks/useEnvironmentQuery';
import { useFieldErrors } from '../../hooks/useFieldErrors';
import { workspaceDraft, workspacePayload } from '../../utils/workspaceSetting';
import { formatDateTime, toDateTimeLocal } from '../../utils/formatDate';
import { saveBlob } from '../../utils/download';
import { useApiError, useTaskProblemText } from '../../hooks/useApiError';
import { useDiscardGuard } from '../../hooks/useUnsavedChanges';

export default function ChallengeList({ onAddTask, onEditTask }) {
  const { t } = useTranslation();
  const { showToast, confirm, selectedChallenge } = useApp();
  const { currentUser } = useAuth();
  // Import, edit, delete and audit download are admin-only routes; the jury does not see them
  const isAdmin = currentUser?.role === 'admin';
  // Finalising a stage or the challenge is the jury's decision; those routes are jury-only
  const isJury = currentUser?.role === 'jury';
  const { mutateAsync: updateChallengeAct, isPending: isUpdatingChallenge } = useUpdateChallenge();
  const { mutateAsync: deleteChallengeAct, isPending: isDeletingChallenge } = useDeleteChallenge();
  const { mutateAsync: finalizeChallengeAct, isPending: isFinalizingChallenge } =
    useFinalizeChallenge();
  const { mutateAsync: toggleRevealChallengeAct, isPending: isRevealingChallenge } =
    useToggleRevealChallenge();
  const { mutateAsync: archiveToggleAct, isPending: isArchiving } = useArchiveToggle();
  const { mutateAsync: exportChallengeAct, isPending: isExporting } = useExportChallenge();
  const { mutateAsync: importChallengeAct } = useImportChallenge();
  const { mutateAsync: createStageAct, isPending: isCreatingStagePending } = useCreateStage();
  const { mutateAsync: updateStageAct, isPending: isUpdatingStage } = useUpdateStage();
  const { mutateAsync: deleteStageAct, isPending: isDeletingStage } = useDeleteStage();
  const { mutateAsync: finalizeStageAct, isPending: isFinalizingStage } = useFinalizeStage();
  const { mutateAsync: toggleRevealStageAct, isPending: isRevealingStage } = useToggleRevealStage();
  const { mutateAsync: deleteTaskAct, isPending: isDeletingTask } = useDeleteTask();

  const { showApiError } = useApiError();
  const problemText = useTaskProblemText();
  const confirmDiscard = useDiscardGuard();

  const API_BASE = '/api';

  const importFileRef = useRef(null);
  const [expandedErrorTask, setExpandedErrorTask] = useState(null);

  const [editingChallenge, setEditingChallenge] = useState(null);
  const [workspaceEdit, setWorkspaceEdit] = useState(() => workspaceDraft(null));
  // What the editors held when they opened, to tell unsaved changes apart
  const [editSnapshot, setEditSnapshot] = useState('');
  const [stageSnapshot, setStageSnapshot] = useState('');
  const workspaceErrors = useFieldErrors('workspace.');
  const [workspacesChallenge, setWorkspacesChallenge] = useState(null);

  const [challengesPage, setChallengesPage] = useState(1);
  const { data: paginatedData } = useAdminChallengesQuery(challengesPage);
  const paginatedChallengesList = paginatedData?.items || [];
  const challengesTotal = paginatedData?.total || 0;
  const challengesPages = paginatedData?.pages || 1;

  const [isCreatingStage, setIsCreatingStage] = useState(false);
  const [editingStage, setEditingStage] = useState(null);
  // The competition as it was when its stage was opened, for when it leaves the current page
  const [stageChallengeAtOpen, setStageChallengeAtOpen] = useState(null);
  const [stageChallengeId, setStageChallengeId] = useState(null);
  const [stageForm, setStageForm] = useState({
    title: '',
    stage_number: '',
    start_time: '',
    end_time: '',
    reveal_results: false,
  });

  // Views read the list's copies, which refetch after an extension moves the end
  const latest = (challenge) =>
    challenge &&
    (paginatedChallengesList.find((c) => String(c.id) === String(challenge.id)) || challenge);
  const editedChallenge = latest(editingChallenge);
  const stageChallenge =
    paginatedChallengesList.find((c) => String(c.id) === String(stageChallengeId)) ||
    stageChallengeAtOpen;
  const editedStage =
    editingStage &&
    (stageChallenge?.stages?.find((st) => st.id === editingStage.id) || editingStage);

  const workspaceCatalog = useWorkspaceCatalogQuery(isAdmin && Boolean(editingChallenge));
  const workspaceEnvironments = useEnvironmentsQuery(editingChallenge?.id, {
    enabled: isAdmin && workspaceEdit.enabled && workspacesOffered(workspaceCatalog),
  });

  const openEditChallenge = (challenge) => {
    const draft = workspaceDraft(challenge.workspace);
    setEditingChallenge(challenge);
    setWorkspaceEdit(draft);
    setEditSnapshot(JSON.stringify([challenge, draft]));
    workspaceErrors.reset();
  };
  const editDirty =
    Boolean(editingChallenge) && JSON.stringify([editingChallenge, workspaceEdit]) !== editSnapshot;

  const [finalizingStage, setFinalizingStage] = useState(null);
  const [stageFinalizeForm, setStageFinalizeForm] = useState({
    reveal_results: false,
  });

  const [downloadingAudit, setDownloadingAudit] = useState(null);

  const [finalizingChallenge, setFinalizingChallenge] = useState(null);
  const [challengeFinalizeForm, setChallengeFinalizeForm] = useState({
    reveal_results: false,
  });

  const handleUpdateChallenge = async (id, updated) => {
    let result = { success: false };
    try {
      const res = await updateChallengeAct({ id, ...updated });
      if (res.ok) {
        showToast(t('admin.notifications.competition_updated'));
        result = { success: true };
      } else {
        showApiError(res.data, 'admin.notifications.competition_update_failed');
      }
    } catch (error) {
      workspaceErrors.capture(error);
      showApiError(error, 'admin.notifications.network_error_update_competition');
    }
    return result;
  };

  const handleDeleteChallenge = async (id, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_competition_title'),
      message: t('admin.confirm.delete_competition_message', { title }),
    });
    if (!ok) return;
    try {
      const res = await deleteChallengeAct(id);
      if (res.ok) {
        showToast(t('admin.notifications.competition_deleted', { title }));
        if (editingChallenge?.id === id) setEditingChallenge(null);
      } else {
        showApiError(res.data, 'admin.notifications.competition_delete_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error_delete_competition');
    }
  };

  const handleFinalizeSetup = (challenge) => {
    setFinalizingChallenge(challenge);
    setChallengeFinalizeForm({ reveal_results: false });
  };

  const handleSaveFinalizeChallenge = async () => {
    if (!finalizingChallenge) return;
    try {
      const res = await finalizeChallengeAct({
        id: finalizingChallenge.id,
        reveal_results: challengeFinalizeForm.reveal_results,
      });
      if (res.ok) {
        showToast(t('admin.notifications.scores_finalized'));
        setFinalizingChallenge(null);
      } else {
        showApiError(res.data, 'admin.notifications.scores_finalize_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error_finalize_scores');
    }
  };

  const handleToggleRevealChallenge = async (id, currentRevealResults) => {
    const nextVal = !currentRevealResults;
    try {
      const res = await toggleRevealChallengeAct({ id, reveal_results: nextVal });
      if (res.ok) {
        showToast(
          nextVal
            ? t('admin.notifications.results_revealed', 'Results revealed successfully.')
            : t('admin.notifications.results_hidden', 'Results hidden successfully.'),
        );
      } else {
        showApiError(res.data, '', t('admin.notifications.toggle_reveal_failed'));
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error');
    }
  };

  const handleToggleRevealStage = async (challengeId, stageId, currentRevealResults) => {
    const nextVal = !currentRevealResults;
    try {
      const res = await toggleRevealStageAct({ challengeId, stageId, reveal_results: nextVal });
      if (res.ok) {
        showToast(
          nextVal
            ? t('admin.notifications.stage_results_revealed', 'Stage results revealed.')
            : t('admin.notifications.stage_results_hidden', 'Stage results hidden.'),
        );
      } else {
        showApiError(res.data, '', t('admin.notifications.toggle_stage_reveal_failed'));
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error');
    }
  };

  const handleArchiveToggle = async (id) => {
    try {
      const res = await archiveToggleAct(id);
      if (res.ok) {
        showToast(res.data?.message || t('admin.notifications.archive_toggle_success'));
      } else {
        showApiError(res.data, 'admin.notifications.archive_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error');
    }
  };

  const initCreateStage = (challenge) => {
    setStageChallengeId(challenge.id);
    setStageChallengeAtOpen(challenge);
    setEditingStage(null);
    const form = {
      title: '',
      stage_number: '',
      start_time: '',
      end_time: '',
      reveal_results: false,
    };
    setStageForm(form);
    setStageSnapshot(JSON.stringify(form));
    setIsCreatingStage(true);
  };

  const initEditStage = (challenge, stage) => {
    setIsCreatingStage(false);
    setStageChallengeId(challenge.id);
    setStageChallengeAtOpen(challenge);
    setEditingStage(stage);
    const form = {
      title: stage.title || '',
      stage_number:
        stage.stage_number !== null && stage.stage_number !== undefined
          ? stage.stage_number.toString()
          : '',
      start_time: toDateTimeLocal(stage.start_time),
      end_time: toDateTimeLocal(stage.end_time),
      reveal_results: !!stage.reveal_results,
    };
    setStageForm(form);
    setStageSnapshot(JSON.stringify(form));
  };
  const stageDirty = JSON.stringify(stageForm) !== stageSnapshot;

  const closeStageForm = () => {
    setIsCreatingStage(false);
    setEditingStage(null);
  };

  const initFinalizeStage = (challengeId, stage) => {
    setStageChallengeId(challengeId);
    setFinalizingStage(stage);
    setStageFinalizeForm({ reveal_results: true });
  };

  const handleSaveCreateStage = async (e) => {
    e.preventDefault();
    const payload = {
      title: stageForm.title,
      stage_number: stageForm.stage_number ? parseInt(stageForm.stage_number) : null,
      start_time: stageForm.start_time,
      end_time: stageForm.end_time,
    };
    try {
      const res = await createStageAct({ challengeId: stageChallengeId, ...payload });
      if (res.ok) {
        showToast(t('admin.notifications.stage_created'));
        setIsCreatingStage(false);
      } else {
        showApiError(res.data, 'admin.notifications.stage_create_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error_create_stage');
    }
  };

  const handleSaveUpdateStage = async (e) => {
    e.preventDefault();
    const payload = {
      title: stageForm.title,
      stage_number: stageForm.stage_number ? parseInt(stageForm.stage_number) : null,
      reveal_results: !!stageForm.reveal_results,
    };
    // Unchanged times stay out: the form drops their seconds, which would move a locked window
    for (const key of ['start_time', 'end_time']) {
      if (stageForm[key] !== toDateTimeLocal(editedStage[key])) payload[key] = stageForm[key];
    }
    try {
      const res = await updateStageAct({
        challengeId: stageChallengeId,
        stageId: editingStage.id,
        ...payload,
      });
      if (res.ok) {
        showToast(t('admin.notifications.stage_updated'));
        setEditingStage(null);
      } else {
        showApiError(res.data, 'admin.notifications.stage_update_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error_update_stage');
    }
  };

  const handleDeleteStage = async (challengeId, stageId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_stage_title'),
      message: t('admin.confirm.delete_stage_message', { title }),
    });
    if (!ok) return;
    try {
      const res = await deleteStageAct({ challengeId, stageId });
      if (res.ok) {
        showToast(t('admin.notifications.stage_deleted', { title }));
      } else {
        showApiError(res.data, 'admin.notifications.stage_delete_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error_delete_stage');
    }
  };

  const handleSaveFinalizeStage = async () => {
    try {
      const res = await finalizeStageAct({
        challengeId: stageChallengeId,
        stageId: finalizingStage.id,
        reveal_results: stageFinalizeForm.reveal_results,
      });
      if (res.ok) {
        showToast(t('admin.notifications.stage_finalized'));
        setFinalizingStage(null);
      } else {
        showApiError(res.data, 'admin.notifications.stage_finalize_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error_finalize_stage');
    }
  };

  const handleDeleteTask = async (taskId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_task_title'),
      message: t('admin.confirm.delete_task_message', { title }),
    });
    if (!ok) return;
    try {
      const res = await deleteTaskAct(taskId);
      if (res.ok) {
        showToast(t('admin.notifications.task_deleted', { title }));
      } else {
        showApiError(res.data, 'admin.notifications.task_delete_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error');
    }
  };

  const handleDownloadScores = async (challengeId, challengeTitle) => {
    try {
      const res = await api.fetch(
        `${API_BASE}/admin/challenges/${challengeId}/download-scores-csv`,
        { headers: {} },
      );
      if (!res.ok) {
        const errData = await res.json();
        showApiError(errData, 'admin.notifications.download_scores_failed');
        return;
      }
      const blob = await res.blob();
      const filename = `scores_${challengeTitle.replace(/\s+/g, '_')}.csv`;
      saveBlob(blob, filename);
      showToast(t('admin.notifications.scores_csv_downloaded'));
    } catch {
      showToast(t('admin.notifications.download_scores_failed'), 'rose');
    }
  };

  const handleDownloadSubmissionsZip = async (
    challengeId,
    challengeTitle,
    stageId = null,
    stageTitle = null,
  ) => {
    try {
      let url = `${API_BASE}/admin/challenges/${challengeId}/download-submissions-zip`;
      if (stageId) url += `?stage_id=${stageId}`;
      const res = await api.fetch(url, { headers: {} });
      if (!res.ok) {
        const errData = await res.json();
        showApiError(errData, 'admin.notifications.download_submissions_failed');
        return;
      }
      const blob = await res.blob();
      let filename = `submissions_${challengeTitle.replace(/\s+/g, '_')}`;
      if (stageTitle) filename += `_stage_${stageTitle.replace(/\s+/g, '_')}`;
      filename += '.zip';
      saveBlob(blob, filename);
      showToast(t('admin.notifications.submissions_zip_downloaded'));
    } catch {
      showToast(t('admin.notifications.download_submissions_failed'), 'rose');
    }
  };

  const handleDownloadAuditLogs = async (challengeId, challengeTitle) => {
    setDownloadingAudit(challengeId);
    try {
      const res = await ChallengeService.downloadAuditLogs(challengeId);
      if (!res.ok) {
        showToast(
          t('admin.notifications.download_audits_failed', 'Download audit logs failed'),
          'rose',
        );
        return;
      }
      const blob = await res.blob();
      const filename = `audits_${challengeTitle.replace(/\s+/g, '_')}.json`;
      saveBlob(blob, filename);
      showToast(
        t('admin.notifications.audits_json_downloaded', 'Audit logs downloaded successfully'),
      );
    } catch {
      showToast(
        t('admin.notifications.download_audits_failed', 'Download audit logs failed'),
        'rose',
      );
    } finally {
      setDownloadingAudit(null);
    }
  };

  const handleExportChallenge = async (challengeId, challengeTitle) => {
    try {
      const result = await exportChallengeAct(challengeId);
      if (!result.ok) {
        showToast(t('admin.notifications.export_challenge_failed'), 'rose');
        return;
      }
      const blob = await result.res.blob();
      const filename = `challenge_${challengeTitle.replace(/\s+/g, '_')}.zip`;
      saveBlob(blob, filename);
      showToast(t('admin.notifications.challenge_exported'));
    } catch {
      showToast(t('admin.notifications.export_challenge_failed'), 'rose');
    }
  };

  const handleImportChallenge = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await importChallengeAct(formData);
      if (res.ok) {
        showToast(t('admin.notifications.challenge_imported'));
      } else {
        showApiError(res.data, '', t('admin.notifications.import_challenge_failed'));
      }
    } catch (error) {
      showApiError(error, '', t('admin.notifications.import_challenge_failed'));
    }
    e.target.value = '';
  };

  const submitEditChallenge = async () => {
    if (isUpdatingChallenge) return;
    const body = { ...editingChallenge };
    delete body.workspace;
    // As for stages, unchanged times stay out of the update
    for (const key of ['start_time', 'end_time']) {
      if (toDateTimeLocal(body[key]) === toDateTimeLocal(editedChallenge[key])) {
        delete body[key];
      }
    }
    if (workspacesOffered(workspaceCatalog)) {
      body.workspace = workspacePayload(workspaceEdit);
    }
    workspaceErrors.reset();
    const res = await handleUpdateChallenge(editingChallenge.id, body);
    if (res.success) setEditingChallenge(null);
  };

  const openWorkspaceSettings = async () => {
    if (!(await confirmDiscard(stageDirty))) return;
    closeStageForm();
    openEditChallenge(stageChallenge);
  };

  return (
    <div className="flex flex-col gap-6">
      {workspacesChallenge ? (
        <WorkspacesPanel
          challenge={latest(workspacesChallenge)}
          readOnly={!isAdmin}
          onClose={() => setWorkspacesChallenge(null)}
        />
      ) : editingChallenge ? (
        <FormView
          title={t('admin.edit_competition', { title: editingChallenge.title })}
          onSubmit={submitEditChallenge}
          onCancel={() => setEditingChallenge(null)}
          dirty={editDirty}
          errors={workspaceErrors.errors}
          submitLabel={t('admin.stages.save_changes_btn')}
          submitting={isUpdatingChallenge}
        >
          <CompetitionFields
            value={editingChallenge}
            onChange={(patch) => setEditingChallenge({ ...editingChallenge, ...patch })}
            idPrefix="edit"
            testStage={editingChallenge.stages?.find((s) => s.is_test)}
          />
          <WorkspaceSettingsSection
            draft={workspaceEdit}
            onChange={setWorkspaceEdit}
            catalog={workspaceCatalog}
            timezone={editingChallenge.timezone || 'UTC'}
            environments={workspaceEnvironments.data}
            errors={workspaceErrors.errors}
            onFieldEdit={workspaceErrors.clear}
          />
        </FormView>
      ) : isCreatingStage || editingStage ? (
        <FormView
          testId="stage-form"
          title={
            isCreatingStage
              ? t('admin.stages.create_stage_modal_title')
              : t('admin.stages.edit_stage_modal_title', { title: editingStage?.title })
          }
          onSubmit={isCreatingStage ? handleSaveCreateStage : handleSaveUpdateStage}
          onCancel={closeStageForm}
          dirty={stageDirty}
          submitLabel={
            isCreatingStage
              ? t('admin.stages.create_stage_btn')
              : t('admin.stages.save_changes_btn')
          }
          submitting={isCreatingStagePending || isUpdatingStage}
        >
          <InputField
            label={t('admin.stages.stage_title_label')}
            value={stageForm.title}
            onChange={(e) => setStageForm({ ...stageForm, title: e.target.value })}
            required
          />
          <InputField
            label={t('admin.stages.stage_number_optional')}
            type="number"
            value={stageForm.stage_number}
            onChange={(e) => setStageForm({ ...stageForm, stage_number: e.target.value })}
            placeholder={t('admin.stages.edit_stage_number_placeholder')}
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <InputField
              label={t('admin.stages.start_time_label')}
              type="datetime-local"
              value={stageForm.start_time}
              onChange={(e) => setStageForm({ ...stageForm, start_time: e.target.value })}
              required
            />
            <InputField
              label={t('admin.stages.end_time_label')}
              type="datetime-local"
              value={stageForm.end_time}
              onChange={(e) => setStageForm({ ...stageForm, end_time: e.target.value })}
              required
            />
          </div>
          {stageChallenge?.workspace?.enabled && (
            <Notice>
              {t('admin.stages.workspace_hint')}{' '}
              {isAdmin && (
                <button
                  type="button"
                  className="underline font-semibold"
                  data-return-id={`competition-edit-${stageChallenge.id}`}
                  onClick={openWorkspaceSettings}
                >
                  {t('admin.stages.workspace_settings_link')}
                </button>
              )}
            </Notice>
          )}
        </FormView>
      ) : (
        <div className="flex flex-col gap-6">
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <h1 className="text-xl font-bold text-white">{t('admin.active_competitions')}</h1>
            <div className="flex gap-2">
              {isAdmin && (
                <>
                  <input
                    ref={importFileRef}
                    type="file"
                    accept=".json,.zip"
                    className="hidden"
                    onChange={handleImportChallenge}
                  />
                  <Button variant="secondary" onClick={() => importFileRef.current?.click()}>
                    {t('admin.import_challenge', 'Import Challenge')}
                  </Button>
                </>
              )}
              <Button
                variant="primary"
                data-return-id="task-add"
                onClick={() => onAddTask && onAddTask(selectedChallenge?.id)}
                disabled={!selectedChallenge}
              >
                <Plus size={16} />
                {t('admin.add_task')}
              </Button>
            </div>
          </div>

          {paginatedChallengesList.length === 0 ? (
            <p className="text-xs text-slate-500 italic">{t('admin.no_competitions_created')}</p>
          ) : (
            paginatedChallengesList.map((c) => (
              <div key={c.id} className="admin-card p-6 flex flex-col gap-4">
                <div className="flex flex-wrap justify-between items-start gap-4">
                  <div>
                    <h2 className="text-lg font-bold text-white flex items-center gap-2">
                      {c.title}
                      {(() => {
                        const now = new Date();
                        const start = c.start_time ? new Date(c.start_time) : null;
                        const end = c.end_time ? new Date(c.end_time) : null;
                        let compStatus;
                        if (c.is_archived) {
                          compStatus = 'archived';
                        } else if (c.is_frozen) {
                          compStatus = 'frozen';
                        } else if (c.scores_finalized && c.reveal_results) {
                          compStatus = 'public';
                        } else if (c.scores_finalized && !c.reveal_results) {
                          compStatus = 'internal';
                        } else if (start && now < start) {
                          compStatus = 'future';
                        } else if (end && now > end) {
                          compStatus = 'grading';
                        } else {
                          compStatus = 'active';
                        }
                        return <Badge status={compStatus} />;
                      })()}
                    </h2>
                    <p className="text-xs text-slate-400 mt-1">
                      {c.description || t('admin.no_description')}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {isAdmin && (
                      <Button
                        variant="secondary"
                        data-return-id={`competition-edit-${c.id}`}
                        onClick={() => openEditChallenge(c)}
                      >
                        {t('admin.stages.edit')}
                      </Button>
                    )}
                    {c.workspace && (
                      <Button
                        variant="secondary"
                        data-return-id={`competition-workspaces-${c.id}`}
                        onClick={() => setWorkspacesChallenge(c)}
                      >
                        {t('environment.view.button')}
                      </Button>
                    )}
                    <Button
                      variant="secondary"
                      onClick={() => handleArchiveToggle(c.id)}
                      disabled={isArchiving}
                      isLoading={isArchiving}
                    >
                      {c.is_archived ? t('admin.restore') : t('admin.archive')}
                    </Button>

                    {c.scores_finalized && (
                      <Button variant="accent" onClick={() => handleDownloadScores(c.id, c.title)}>
                        {t('admin.download_csv_scores_short', 'Scores (CSV)')}
                      </Button>
                    )}

                    {(c.scores_finalized ||
                      (c.end_time ? new Date(c.end_time) <= new Date() : false)) && (
                      <Button
                        variant="accent"
                        onClick={() => handleDownloadSubmissionsZip(c.id, c.title)}
                      >
                        {c.scores_finalized
                          ? t('admin.download_submissions_zip_short', 'Submissions (ZIP)')
                          : t(
                              'admin.download_submissions_zip_short_blinded',
                              'Submissions (ZIP) (Blinded)',
                            )}
                      </Button>
                    )}

                    {c.scores_finalized && (
                      <>
                        {isAdmin && (
                          <Button
                            variant="accent"
                            onClick={() => handleDownloadAuditLogs(c.id, c.title)}
                            disabled={downloadingAudit === c.id}
                            isLoading={downloadingAudit === c.id}
                          >
                            {t('admin.download_audits_json_short', 'Audits (JSON)')}
                          </Button>
                        )}
                        <Button
                          variant="secondary"
                          onClick={() => handleToggleRevealChallenge(c.id, c.reveal_results)}
                          disabled={isRevealingChallenge}
                          isLoading={isRevealingChallenge}
                        >
                          {c.reveal_results
                            ? t('admin.hide_results', 'Hide')
                            : t('admin.reveal_results', 'Reveal')}
                        </Button>
                      </>
                    )}
                    {isJury &&
                      !c.scores_finalized &&
                      (c.end_time ? new Date(c.end_time) <= new Date() : false) && (
                        <Button
                          variant="accent"
                          onClick={() => handleFinalizeSetup(c)}
                          disabled={c.stages && c.stages.some((st) => !st.is_finalized)}
                          title={
                            c.stages && c.stages.some((st) => !st.is_finalized)
                              ? t('leaderboard.finalize_disabled_tooltip')
                              : ''
                          }
                        >
                          {t('admin.finalize_short', 'Finalize')}
                        </Button>
                      )}
                    <Button
                      variant="secondary"
                      onClick={() => handleExportChallenge(c.id, c.title)}
                      disabled={isExporting}
                      isLoading={isExporting}
                    >
                      {t('admin.export_short', 'Export')}
                    </Button>
                    {isAdmin && (
                      <Button
                        variant="danger"
                        onClick={() => handleDeleteChallenge(c.id, c.title)}
                        disabled={isDeletingChallenge}
                        isLoading={isDeletingChallenge}
                      >
                        {t('admin.stages.delete')}
                      </Button>
                    )}
                  </div>
                </div>

                <div className="border-t border-white/5 pt-4 mt-2">
                  <div className="flex justify-between items-center mb-3">
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                      {t('admin.tasks_in_competition', {
                        count: c.tasks ? c.tasks.length : 0,
                      })}
                    </h3>
                    <Button
                      variant="primary"
                      className="py-1 px-3 text-[10px]"
                      data-return-id={`task-add-${c.id}`}
                      onClick={() => onAddTask && onAddTask(c.id)}
                    >
                      <Plus size={14} />
                      {t('admin.add_task')}
                    </Button>
                  </div>
                  {c.tasks?.length === 0 ? (
                    <p className="text-xs text-slate-500 italic">{t('admin.no_tasks_created')}</p>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {c.tasks?.map((task) => (
                        <div
                          key={task.id}
                          className="p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs"
                        >
                          <div className="flex flex-wrap justify-between items-center gap-4">
                            <div className="min-w-0 flex-1">
                              <span className="font-bold text-slate-200">
                                {task.problem_codes?.length > 0 && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setExpandedErrorTask(
                                        expandedErrorTask === task.id ? null : task.id,
                                      )
                                    }
                                    className="inline mr-1 align-middle"
                                    aria-label={t('admin.task_problems_title')}
                                  >
                                    <AlertTriangle className="w-4 h-4 text-amber-400 hover:text-amber-300 transition-colors" />
                                  </button>
                                )}
                                {task.title}
                              </span>
                              <span className="text-[10px] text-slate-500 ml-2">
                                {t('admin.public_eval_split', {
                                  percentage: task.public_eval_percentage ?? 30,
                                })}
                              </span>
                              {expandedErrorTask === task.id && task.problem_codes?.length > 0 && (
                                <div className="mt-2 p-2 bg-amber-900/20 border border-amber-500/30 rounded text-[11px] text-amber-300 whitespace-pre-wrap break-words">
                                  {task.problem_codes.map((code) => (
                                    <div key={code}>{problemText(task, code)}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-2">
                              <Button
                                variant="secondary"
                                data-return-id={`task-edit-${task.id}`}
                                onClick={() => onEditTask && onEditTask(task)}
                              >
                                {t('admin.edit_config')}
                              </Button>
                              <Button
                                variant="danger"
                                onClick={() => handleDeleteTask(task.id, task.title)}
                                disabled={isDeletingTask}
                                isLoading={isDeletingTask}
                              >
                                {t('admin.stages.delete')}
                              </Button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="border-t border-white/5 pt-4 mt-2">
                  <div className="flex justify-between items-center mb-3">
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                      {t('admin.stages.stages_in_competition', {
                        count: c.stages ? c.stages.length : 0,
                      })}
                    </h3>
                    <Button
                      variant="primary"
                      className="py-1 px-3 text-[10px]"
                      data-return-id={`stage-add-${c.id}`}
                      onClick={() => initCreateStage(c)}
                    >
                      <Plus size={14} />
                      {t('admin.stages.add_stage')}
                    </Button>
                  </div>
                  {c.stages?.length === 0 ? (
                    <p className="text-xs text-slate-500 italic">{t('admin.stages.no_stages')}</p>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {c.stages?.map((st) => (
                        <div
                          key={st.id}
                          className="flex flex-wrap justify-between items-center gap-3 p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs"
                        >
                          <div className="flex items-center flex-wrap gap-x-2 gap-y-1">
                            <span className="font-bold text-slate-200">
                              {t('admin.stages.stage_label', {
                                number: st.stage_number,
                                title: st.title,
                              })}
                            </span>
                            <span className="text-[10px] text-indigo-400">
                              {formatDateTime(st.start_time, c.timezone)} {t('common.to')}{' '}
                              {formatDateTime(st.end_time, c.timezone)}
                            </span>
                            {(() => {
                              const now = new Date();
                              const start = new Date(st.start_time);
                              const end = new Date(st.end_time);
                              let stageStatus;
                              if (st.is_finalized && st.reveal_results) {
                                stageStatus = 'public';
                              } else if (st.is_finalized && !st.reveal_results) {
                                stageStatus = 'internal';
                              } else if (now < start) {
                                stageStatus = 'future';
                              } else if (now > end) {
                                stageStatus = 'grading';
                              } else {
                                stageStatus = 'active';
                              }
                              return <Badge status={stageStatus} />;
                            })()}
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="secondary"
                              className="py-1 px-2.5"
                              data-return-id={`stage-edit-${st.id}`}
                              onClick={() => initEditStage(c, st)}
                            >
                              {t('admin.stages.edit')}
                            </Button>
                            {isJury &&
                              !st.is_finalized &&
                              (st.end_time ? new Date(st.end_time) <= new Date() : false) && (
                                <Button
                                  variant="accent"
                                  className="py-1 px-2.5"
                                  onClick={() => initFinalizeStage(c.id, st)}
                                >
                                  {t('admin.stages.finalize')}
                                </Button>
                              )}
                            {st.is_finalized && (
                              <Button
                                variant="secondary"
                                className="py-1 px-2.5"
                                onClick={() =>
                                  handleToggleRevealStage(c.id, st.id, st.reveal_results)
                                }
                                disabled={isRevealingStage}
                                isLoading={isRevealingStage}
                              >
                                {st.reveal_results
                                  ? t('admin.hide_results', 'Hide')
                                  : t('admin.reveal_results', 'Reveal')}
                              </Button>
                            )}

                            {(c.scores_finalized ||
                              st.is_finalized ||
                              (st.end_time ? new Date(st.end_time) <= new Date() : false)) && (
                              <Button
                                variant="accent"
                                className="py-1 px-2.5"
                                onClick={() =>
                                  handleDownloadSubmissionsZip(c.id, c.title, st.id, st.title)
                                }
                              >
                                {c.scores_finalized
                                  ? t('admin.download_submissions_stage', 'Download')
                                  : t(
                                      'admin.download_submissions_stage_blinded',
                                      'Download (Blinded)',
                                    )}
                              </Button>
                            )}
                            <Button
                              variant="danger"
                              className="py-1 px-2.5"
                              onClick={() => handleDeleteStage(c.id, st.id, st.title)}
                              disabled={isDeletingStage}
                              isLoading={isDeletingStage}
                            >
                              {t('admin.stages.delete')}
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          <Pagination
            page={challengesPage}
            pages={challengesPages}
            total={challengesTotal}
            perPage={5}
            onPageChange={setChallengesPage}
            itemName={t('admin.competitions_pagination_item')}
          />
        </div>
      )}

      <FinalizeDialog
        isOpen={Boolean(finalizingStage)}
        title={t('admin.stages.finalize_stage_modal_title', { title: finalizingStage?.title })}
        revealLabel={t(
          'admin.stages.reveal_results_and_points_desc',
          'Reveal results and points to competitors (otherwise finalization is jury-internal only)',
        )}
        revealId="stage-reveal-results-and-points"
        reveal={stageFinalizeForm.reveal_results}
        onRevealChange={(checked) => setStageFinalizeForm({ reveal_results: checked })}
        confirmLabel={t('admin.stages.finalize_stage_btn')}
        isPending={isFinalizingStage}
        onConfirm={handleSaveFinalizeStage}
        onClose={() => setFinalizingStage(null)}
      />

      <FinalizeDialog
        isOpen={Boolean(finalizingChallenge)}
        title={t('admin.finalize_competition_title', { title: finalizingChallenge?.title })}
        revealLabel={t(
          'admin.reveal_results_label',
          'Reveal private scores and competitor identities immediately',
        )}
        revealId="challenge-reveal-results"
        reveal={challengeFinalizeForm.reveal_results}
        onRevealChange={(checked) => setChallengeFinalizeForm({ reveal_results: checked })}
        confirmLabel={t('admin.finalize_short', 'Finalize')}
        isPending={isFinalizingChallenge}
        onConfirm={handleSaveFinalizeChallenge}
        onClose={() => setFinalizingChallenge(null)}
      />
    </div>
  );
}
