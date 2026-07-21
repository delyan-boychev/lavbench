import React, { useState, useRef } from 'react';
import api from '../../services/ApiService';
import ChallengeService from '../../services/ChallengeService';
import { useTranslation } from 'react-i18next';
import { useApp } from '../../context/AppContext';
import { useQueryClient } from '@tanstack/react-query';
import useMutation from '../../hooks/useMutation';
import { useAdminChallengesQuery } from '../../hooks/useAdminChallengesQuery';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import InputField from '../ui/InputField';
import SelectField from '../ui/SelectField';
import Pagination from '../ui/Pagination';
import ToggleField from '../ui/ToggleField';
import { Plus, AlertTriangle } from 'lucide-react';
import { TIMEZONES } from '../../utils/timezones';
import { formatDateTime } from '../../utils/formatDate';

export default function ChallengeList({ onAddTask, onEditTask }) {
  const { t } = useTranslation();
  const { showToast, confirm, selectedChallenge, fetchChallenges } = useApp();
  const { isLoading, run } = useMutation();

  const showApiError = (data, defaultTranslationKey, defaultText = '') => {
    if (data?.code) {
      showToast(t(`api.${data.code}`, data.error || t(defaultTranslationKey, defaultText)), 'rose');
    } else {
      showToast(data?.error || t(defaultTranslationKey, defaultText), 'rose');
    }
  };

  const API_BASE = '/api';

  const importFileRef = useRef(null);

  const [editingChallenge, setEditingChallenge] = useState(null);

  const queryClient = useQueryClient();
  const [challengesPage, setChallengesPage] = useState(1);
  const { data: paginatedData } = useAdminChallengesQuery(challengesPage);
  const paginatedChallengesList = paginatedData?.items || [];
  const challengesTotal = paginatedData?.total || 0;
  const challengesPages = paginatedData?.pages || 1;

  const [isCreatingStage, setIsCreatingStage] = useState(false);
  const [editingStage, setEditingStage] = useState(null);
  const [stageChallengeId, setStageChallengeId] = useState(null);
  const [stageForm, setStageForm] = useState({
    title: '',
    stage_number: '',
    start_time: '',
    end_time: '',
    reveal_results: false,
  });

  const [finalizingStage, setFinalizingStage] = useState(null);
  const [stageFinalizeForm, setStageFinalizeForm] = useState({
    reveal_results: false,
  });

  const [finalizingChallenge, setFinalizingChallenge] = useState(null);
  const [challengeFinalizeForm, setChallengeFinalizeForm] = useState({
    reveal_results: false,
  });

  const invalidateChallenges = () => {
    queryClient.invalidateQueries({ queryKey: ['admin-challenges'] });
    queryClient.invalidateQueries({ queryKey: ['challenges'] });
  };

  const handleUpdateChallenge = async (id, updated) => {
    let result = { success: false };
    try {
      await run('updateChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updated),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.competition_updated'));
          fetchChallenges();
          invalidateChallenges();
          result = { success: true };
        } else {
          showApiError(data, 'admin.notifications.competition_update_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_update_competition'), 'rose');
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
      await run('deleteChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${id}`, {
          method: 'DELETE',
          headers: {},
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.competition_deleted', { title }));
          if (editingChallenge?.id === id) setEditingChallenge(null);
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, 'admin.notifications.competition_delete_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_delete_competition'), 'rose');
    }
  };

  const handleFinalizeSetup = (challenge) => {
    setFinalizingChallenge(challenge);
    setChallengeFinalizeForm({ reveal_results: false });
  };

  const handleSaveFinalizeChallenge = async (e) => {
    e.preventDefault();
    if (!finalizingChallenge) return;
    try {
      await run('finalizeChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${finalizingChallenge.id}/finalize`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reveal_results: challengeFinalizeForm.reveal_results }),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.scores_finalized'));
          setFinalizingChallenge(null);
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, 'admin.notifications.scores_finalize_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_finalize_scores'), 'rose');
    }
  };

  const handleToggleRevealChallenge = async (id, currentRevealResults) => {
    const nextVal = !currentRevealResults;
    try {
      await run('toggleRevealChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${id}/reveal-results`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reveal_results: nextVal }),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(
            nextVal
              ? t('admin.notifications.results_revealed', 'Results revealed successfully.')
              : t('admin.notifications.results_hidden', 'Results hidden successfully.'),
          );
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, '', 'Failed to toggle reveal');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  const handleToggleRevealStage = async (challengeId, stageId, currentRevealResults) => {
    const nextVal = !currentRevealResults;
    try {
      await run('toggleRevealStage', async () => {
        const res = await api.fetch(
          `${API_BASE}/challenges/${challengeId}/stages/${stageId}/reveal-results`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reveal_results: nextVal }),
          },
        );
        const data = await res.json();
        if (res.ok) {
          showToast(
            nextVal
              ? t('admin.notifications.stage_results_revealed', 'Stage results revealed.')
              : t('admin.notifications.stage_results_hidden', 'Stage results hidden.'),
          );
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, '', 'Failed to toggle stage reveal');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  const handleArchiveToggle = async (id) => {
    try {
      await run('archiveToggle', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${id}/archive`, {
          method: 'POST',
          headers: {},
        });
        const data = await res.json();
        if (res.ok) {
          showToast(data.message || t('admin.notifications.archive_toggle_success'));
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, 'admin.notifications.archive_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  const initCreateStage = (challengeId) => {
    setStageChallengeId(challengeId);
    setStageForm({
      title: '',
      stage_number: '',
      start_time: '',
      end_time: '',
      reveal_results: false,
    });
    setIsCreatingStage(true);
  };

  const initEditStage = (challengeId, stage) => {
    setStageChallengeId(challengeId);
    setEditingStage(stage);
    setStageForm({
      title: stage.title || '',
      stage_number:
        stage.stage_number !== null && stage.stage_number !== undefined
          ? stage.stage_number.toString()
          : '',
      start_time: stage.start_time ? stage.start_time.substring(0, 16) : '',
      end_time: stage.end_time ? stage.end_time.substring(0, 16) : '',
      reveal_results: !!stage.reveal_results,
    });
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
      await run('createStage', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${stageChallengeId}/stages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.stage_created'));
          setIsCreatingStage(false);
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, 'admin.notifications.stage_create_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_create_stage'), 'rose');
    }
  };

  const handleSaveUpdateStage = async (e) => {
    e.preventDefault();
    const payload = {
      title: stageForm.title,
      stage_number: stageForm.stage_number ? parseInt(stageForm.stage_number) : null,
      start_time: stageForm.start_time,
      end_time: stageForm.end_time,
      reveal_results: !!stageForm.reveal_results,
    };
    try {
      await run('updateStage', async () => {
        const res = await api.fetch(
          `${API_BASE}/challenges/${stageChallengeId}/stages/${editingStage.id}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          },
        );
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.stage_updated'));
          setEditingStage(null);
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, 'admin.notifications.stage_update_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_update_stage'), 'rose');
    }
  };

  const handleDeleteStage = async (challengeId, stageId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_stage_title'),
      message: t('admin.confirm.delete_stage_message', { title }),
    });
    if (!ok) return;
    try {
      await run('deleteStage', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${challengeId}/stages/${stageId}`, {
          method: 'DELETE',
          headers: {},
        });
        if (res.ok) {
          showToast(t('admin.notifications.stage_deleted', { title }));
          fetchChallenges();
          invalidateChallenges();
        } else {
          const data = await res.json();
          showApiError(data, 'admin.notifications.stage_delete_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_delete_stage'), 'rose');
    }
  };

  const handleSaveFinalizeStage = async (e) => {
    e.preventDefault();
    const payload = { reveal_results: stageFinalizeForm.reveal_results };
    try {
      await run('finalizeStage', async () => {
        const res = await api.fetch(
          `${API_BASE}/challenges/${stageChallengeId}/stages/${finalizingStage.id}/finalize`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          },
        );
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.stage_finalized'));
          setFinalizingStage(null);
          fetchChallenges();
          invalidateChallenges();
        } else {
          showApiError(data, 'admin.notifications.stage_finalize_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_finalize_stage'), 'rose');
    }
  };

  const handleDeleteTask = async (taskId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_task_title'),
      message: t('admin.confirm.delete_task_message', { title }),
    });
    if (!ok) return;
    try {
      await run('deleteTask', async () => {
        const res = await api.fetch(`${API_BASE}/tasks/${taskId}`, {
          method: 'DELETE',
          headers: {},
        });
        if (res.ok) {
          showToast(t('admin.notifications.task_deleted', { title }));
          fetchChallenges();
          invalidateChallenges();
        } else {
          const data = await res.json();
          showApiError(data, 'admin.notifications.task_delete_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  const handleDownloadScores = async (challengeId, challengeTitle) => {
    try {
      await run('downloadScores', async () => {
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
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast(t('admin.notifications.scores_csv_downloaded'));
      });
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
      await run('downloadSubmissionsZip', async () => {
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
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast(t('admin.notifications.submissions_zip_downloaded'));
      });
    } catch {
      showToast(t('admin.notifications.download_submissions_failed'), 'rose');
    }
  };

  const handleDownloadAuditLogs = async (challengeId, challengeTitle) => {
    try {
      await run('downloadAuditLogs', async () => {
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
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast(
          t('admin.notifications.audits_json_downloaded', 'Audit logs downloaded successfully'),
        );
      });
    } catch {
      showToast(
        t('admin.notifications.download_audits_failed', 'Download audit logs failed'),
        'rose',
      );
    }
  };

  const handleExportChallenge = async (challengeId, challengeTitle) => {
    try {
      await run('exportChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${challengeId}/export`, {
          headers: {},
        });
        if (!res.ok) {
          showToast('Failed to export challenge.', 'rose');
          return;
        }
        const blob = await res.blob();
        const filename = `challenge_${challengeTitle.replace(/\s+/g, '_')}.zip`;
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast('Challenge exported.');
      });
    } catch {
      showToast('Failed to export challenge.', 'rose');
    }
  };

  const handleImportChallenge = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      await run('importChallenge', async () => {
        const res = await api.postForm(`/challenges/import`, formData);
        if (res.ok) {
          showToast('Challenge imported successfully.');
          invalidateChallenges();
        } else {
          showApiError(res.data, '', 'Failed to import challenge.');
        }
      });
    } catch {
      showToast('Failed to import challenge.', 'rose');
    }
    e.target.value = '';
  };

  return (
    <div className="flex flex-col gap-6">
      {!finalizingStage &&
        !finalizingChallenge &&
        (editingChallenge ? (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
            <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
              <h2 className="text-xl font-bold text-white">
                {t('admin.edit_competition', { title: editingChallenge.title })}
              </h2>
            </div>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const res = await handleUpdateChallenge(editingChallenge.id, editingChallenge);
                if (res.success) setEditingChallenge(null);
              }}
              className="flex flex-col gap-4"
            >
              <InputField
                label={t('admin.competition_title')}
                value={editingChallenge.title}
                onChange={(e) =>
                  setEditingChallenge({ ...editingChallenge, title: e.target.value })
                }
                required
              />
              <InputField
                multiline
                label={t('admin.description')}
                value={editingChallenge.description}
                onChange={(e) =>
                  setEditingChallenge({ ...editingChallenge, description: e.target.value })
                }
                rows={4}
              />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <InputField
                  label={t('admin.daily_limits')}
                  type="number"
                  value={editingChallenge.max_eval_requests}
                  onChange={(e) =>
                    setEditingChallenge({
                      ...editingChallenge,
                      max_eval_requests: parseInt(e.target.value) || 0,
                    })
                  }
                />
                <InputField
                  label={t('admin.ram_limit_override')}
                  type="number"
                  value={editingChallenge.ram_limit_mb}
                  onChange={(e) =>
                    setEditingChallenge({
                      ...editingChallenge,
                      ram_limit_mb: parseInt(e.target.value) || 0,
                    })
                  }
                />
                <InputField
                  label={t('admin.time_limit_override')}
                  type="number"
                  value={editingChallenge.time_limit_sec}
                  onChange={(e) =>
                    setEditingChallenge({
                      ...editingChallenge,
                      time_limit_sec: parseInt(e.target.value) || 0,
                    })
                  }
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <InputField
                  label={t('admin.stages.start_time_label')}
                  type="datetime-local"
                  value={
                    editingChallenge.start_time ? editingChallenge.start_time.substring(0, 16) : ''
                  }
                  onChange={(e) =>
                    setEditingChallenge({ ...editingChallenge, start_time: e.target.value })
                  }
                  required
                />
                <InputField
                  label={t('admin.stages.end_time_label')}
                  type="datetime-local"
                  value={
                    editingChallenge.end_time ? editingChallenge.end_time.substring(0, 16) : ''
                  }
                  onChange={(e) =>
                    setEditingChallenge({ ...editingChallenge, end_time: e.target.value })
                  }
                  required
                />
                <SelectField
                  label={t('admin.timezone_choose')}
                  value={editingChallenge.timezone || 'UTC'}
                  onChange={(val) => setEditingChallenge({ ...editingChallenge, timezone: val })}
                  options={TIMEZONES}
                  required
                />
              </div>
              {(() => {
                const existingTestStage = editingChallenge.stages?.find((s) => s.is_test);
                return (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
                    <InputField
                      label={t('admin.test_stage_start')}
                      type="datetime-local"
                      value={
                        editingChallenge.test_stage_start_time !== undefined
                          ? editingChallenge.test_stage_start_time
                          : existingTestStage?.start_time
                            ? existingTestStage.start_time.slice(0, 16)
                            : ''
                      }
                      onChange={(e) =>
                        setEditingChallenge({
                          ...editingChallenge,
                          test_stage_start_time: e.target.value,
                        })
                      }
                    />
                    <InputField
                      label={t('admin.test_stage_end')}
                      type="datetime-local"
                      value={
                        editingChallenge.test_stage_end_time !== undefined
                          ? editingChallenge.test_stage_end_time
                          : existingTestStage?.end_time
                            ? existingTestStage.end_time.slice(0, 16)
                            : ''
                      }
                      onChange={(e) =>
                        setEditingChallenge({
                          ...editingChallenge,
                          test_stage_end_time: e.target.value,
                        })
                      }
                    />
                  </div>
                );
              })()}
              <div className="flex flex-col gap-3 mt-2.5">
                <ToggleField
                  label={t('admin.requires_gpu_sandbox')}
                  id="edit-gpu"
                  checked={editingChallenge.gpu_required}
                  onChange={(e) =>
                    setEditingChallenge({ ...editingChallenge, gpu_required: e.target.checked })
                  }
                />
                <ToggleField
                  label={t('admin.double_blind_eval')}
                  id="edit-double-blind"
                  checked={editingChallenge.double_blind !== false}
                  onChange={(e) =>
                    setEditingChallenge({ ...editingChallenge, double_blind: e.target.checked })
                  }
                />
                <ToggleField
                  label={t('admin.freeze_label')}
                  id="edit-is-frozen"
                  checked={editingChallenge.is_frozen || false}
                  onChange={(e) =>
                    setEditingChallenge({ ...editingChallenge, is_frozen: e.target.checked })
                  }
                />
              </div>
              <div className="flex gap-3 mt-4">
                <Button type="submit" variant="primary">
                  {t('admin.stages.save_changes_btn')}
                </Button>
                <Button onClick={() => setEditingChallenge(null)} variant="secondary">
                  {t('common.cancel')}
                </Button>
              </div>
            </form>
          </div>
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
                <Button
                  variant="primary"
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
                <div
                  key={c.id}
                  className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col gap-4"
                >
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
                      <Button variant="secondary" onClick={() => setEditingChallenge(c)}>
                        {t('admin.stages.edit')}
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() => handleArchiveToggle(c.id)}
                        disabled={isLoading('archiveToggle')}
                      >
                        {c.is_archived ? t('admin.restore') : t('admin.archive')}
                      </Button>

                      {c.scores_finalized && (
                        <Button
                          variant="accent"
                          onClick={() => handleDownloadScores(c.id, c.title)}
                          disabled={isLoading('downloadScores')}
                        >
                          {t('admin.download_csv_scores_short', 'Scores (CSV)')}
                        </Button>
                      )}

                      {(c.scores_finalized ||
                        (c.end_time ? new Date(c.end_time) <= new Date() : false)) && (
                        <Button
                          variant="accent"
                          onClick={() => handleDownloadSubmissionsZip(c.id, c.title)}
                          disabled={isLoading('downloadSubmissionsZip')}
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
                          <Button
                            variant="accent"
                            onClick={() => handleDownloadAuditLogs(c.id, c.title)}
                            disabled={isLoading('downloadAuditLogs')}
                          >
                            {t('admin.download_audits_json_short', 'Audits (JSON)')}
                          </Button>
                          <Button
                            variant="secondary"
                            onClick={() => handleToggleRevealChallenge(c.id, c.reveal_results)}
                            disabled={isLoading('toggleRevealChallenge')}
                          >
                            {c.reveal_results
                              ? t('admin.hide_results', 'Hide')
                              : t('admin.reveal_results', 'Reveal')}
                          </Button>
                        </>
                      )}
                      {!c.scores_finalized &&
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
                        disabled={isLoading('exportChallenge')}
                      >
                        {t('admin.export_short', 'Export')}
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => handleDeleteChallenge(c.id, c.title)}
                        disabled={isLoading('deleteChallenge')}
                      >
                        {t('admin.stages.delete')}
                      </Button>
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
                            className="flex justify-between items-center p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs"
                          >
                            <div>
                              <span className="font-bold text-slate-200">
                                {task.build_error && (
                                  <span title={task.build_error}>
                                    <AlertTriangle className="w-4 h-4 text-amber-400 inline mr-1" />
                                  </span>
                                )}
                                {task.title}
                              </span>
                              <span className="text-[10px] text-slate-500 ml-2">
                                {t('admin.public_eval_split', {
                                  percentage: task.public_eval_percentage || 30,
                                })}
                              </span>
                            </div>
                            <div className="flex gap-2">
                              <Button
                                variant="secondary"
                                onClick={() => onEditTask && onEditTask(task)}
                              >
                                {t('admin.edit_config')}
                              </Button>
                              <Button
                                variant="danger"
                                onClick={() => handleDeleteTask(task.id, task.title)}
                                disabled={isLoading('deleteTask')}
                              >
                                {t('admin.stages.delete')}
                              </Button>
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
                        onClick={() => initCreateStage(c.id)}
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
                            className="flex justify-between items-center p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs"
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
                            <div className="flex gap-2">
                              <Button
                                variant="secondary"
                                className="py-1 px-2.5"
                                onClick={() => initEditStage(c.id, st)}
                              >
                                {t('admin.stages.edit')}
                              </Button>
                              {!st.is_finalized &&
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
                                  disabled={isLoading('toggleRevealStage')}
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
                                  disabled={isLoading('downloadSubmissionsZip')}
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
                                disabled={isLoading('deleteStage')}
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
        ))}

      {isCreatingStage || editingStage ? (
        <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
          <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
            <h2 className="text-xl font-bold text-white">
              {isCreatingStage
                ? t('admin.stages.create_stage_modal_title')
                : t('admin.stages.edit_stage_modal_title', { title: editingStage?.title })}
            </h2>
          </div>

          <form
            onSubmit={isCreatingStage ? handleSaveCreateStage : handleSaveUpdateStage}
            className="flex flex-col gap-4"
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

            <div className="flex gap-3 mt-4">
              <Button
                type="submit"
                variant="primary"
                disabled={isLoading('createStage') || isLoading('updateStage')}
              >
                {isCreatingStage
                  ? t('admin.stages.create_stage_btn')
                  : t('admin.stages.save_changes_btn')}
              </Button>
              <Button
                onClick={() => {
                  setIsCreatingStage(false);
                  setEditingStage(null);
                }}
                variant="secondary"
              >
                {t('common.cancel')}
              </Button>
            </div>
          </form>
        </div>
      ) : null}

      {finalizingStage && (
        <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
          <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
            <h2 className="text-xl font-bold text-white">
              {t('admin.stages.finalize_stage_modal_title', { title: finalizingStage.title })}
            </h2>
          </div>

          <form onSubmit={handleSaveFinalizeStage} className="flex flex-col gap-6">
            <div className="flex flex-col gap-3 p-4 bg-slate-900/40 border border-white/5 rounded-xl">
              <ToggleField
                label={t(
                  'admin.stages.reveal_results_and_points_desc',
                  'Разкриване на резултатите и точките за състезателите (в противен случай завършването е само вътрешно за журито)',
                )}
                id="stage-reveal-results-and-points"
                checked={stageFinalizeForm.reveal_results}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setStageFinalizeForm({ reveal_results: checked });
                }}
              />
            </div>

            <div className="flex gap-3 mt-4">
              <Button type="submit" variant="primary" disabled={isLoading('finalizeStage')}>
                {t('admin.stages.finalize_stage_btn')}
              </Button>
              <Button onClick={() => setFinalizingStage(null)} variant="secondary">
                {t('common.cancel')}
              </Button>
            </div>
          </form>
        </div>
      )}

      {finalizingChallenge && (
        <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
          <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
            <h2 className="text-xl font-bold text-white">
              {t('admin.finalize_competition_title', { title: finalizingChallenge.title })}
            </h2>
          </div>

          <form onSubmit={handleSaveFinalizeChallenge} className="flex flex-col gap-6">
            <div className="flex flex-col gap-3 p-4 bg-slate-900/40 border border-white/5 rounded-xl">
              <ToggleField
                label={t(
                  'admin.reveal_results_label',
                  'Reveal private scores and competitor identities immediately',
                )}
                id="challenge-reveal-results"
                checked={challengeFinalizeForm.reveal_results}
                onChange={(e) =>
                  setChallengeFinalizeForm({
                    ...challengeFinalizeForm,
                    reveal_results: e.target.checked,
                  })
                }
              />
            </div>

            <div className="flex gap-3 mt-4">
              <Button type="submit" variant="primary" disabled={isLoading('finalizeChallenge')}>
                {t('admin.finalize_short', 'Finalize')}
              </Button>
              <Button onClick={() => setFinalizingChallenge(null)} variant="secondary">
                {t('common.cancel')}
              </Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
