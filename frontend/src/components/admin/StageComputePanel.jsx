import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import InputField from '../ui/InputField';
import ToggleField from '../ui/ToggleField';
import SelectField from '../ui/SelectField';
import WorkspaceImagePicker from './WorkspaceImagePicker';
import { useApp } from '../../context/AppContext';
import EnvironmentService from '../../services/EnvironmentService';

const NUMBER_FIELDS = ['cpu_cores', 'memory_gib', 'disk_gib', 'max_attendance', 'retention_days'];
const FORM_FIELDS = [
  'enabled',
  'published',
  'compute_kind',
  'gpu_type',
  'image_id',
  ...NUMBER_FIELDS,
];

function toForm(data) {
  return Object.fromEntries(FORM_FIELDS.map((key) => [key, data?.[key] ?? '']));
}

function toBody(form) {
  const body = { ...form };
  NUMBER_FIELDS.forEach((key) => {
    body[key] = Number(form[key]);
  });
  body.enabled = Boolean(form.enabled);
  body.published = Boolean(form.published);
  body.gpu_type = form.compute_kind === 'GPU' ? form.gpu_type || null : null;
  return body;
}

const PACKAGING_POLL_MS = 3000;

function PackageStatus({ compute }) {
  const { t } = useTranslation();
  const state = compute.package_state || 'NONE';
  const error = compute.package_error || '';
  const tone =
    state === 'READY'
      ? 'text-emerald-400'
      : state === 'FAILED'
        ? 'text-rose-400'
        : 'text-slate-400';
  return (
    <div className={`text-xs ${tone}`} data-testid="package-status">
      <span>{t(`admin.compute.package.${state}`, t('admin.compute.package.NONE'))}</span>
      {state === 'FAILED' && error && (
        <span className="block mt-1">{error.startsWith('ERR_') ? t(`api.${error}`) : error}</span>
      )}
    </div>
  );
}

function TaskPaths({ task, folder, onSaved }) {
  const { t } = useTranslation();
  const { showToast } = useApp();
  const [paths, setPaths] = useState({
    submission_path: task.workspace_submission_path || '',
    notebook_path: task.workspace_notebook_path || '',
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    const res = await EnvironmentService.putTaskWorkspacePaths(task.id, {
      submission_path: paths.submission_path || null,
      notebook_path: paths.notebook_path || null,
    });
    setSaving(false);
    if (!res.ok) {
      showToast(t(`api.${res.data?.code}`, res.data?.error || ''), 'rose');
      return;
    }
    showToast(t('admin.compute.paths_saved'), 'emerald');
    onSaved();
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_1fr_auto] gap-3 items-end">
      <div className="text-xs font-semibold text-slate-300 pb-3">
        {task.title} <span className="font-mono text-slate-500">{folder}/</span>
      </div>
      <InputField
        label={t('admin.compute.submission_path')}
        value={paths.submission_path}
        placeholder={`${folder}/submission.csv`}
        onChange={(e) => setPaths({ ...paths, submission_path: e.target.value })}
      />
      <InputField
        label={t('admin.compute.notebook_path')}
        value={paths.notebook_path}
        placeholder={`${folder}/solution.ipynb`}
        onChange={(e) => setPaths({ ...paths, notebook_path: e.target.value })}
      />
      <Button variant="secondary" onClick={save} isLoading={saving}>
        {t('admin.compute.save_paths')}
      </Button>
    </div>
  );
}

export default function StageComputePanel({ challengeId, stage, tasks }) {
  const { t } = useTranslation();
  const { showToast, confirm } = useApp();
  const queryClient = useQueryClient();
  const queryKey = ['stage-compute', challengeId, stage.id];
  const { data } = useQuery({
    queryKey,
    queryFn: () => EnvironmentService.getStageCompute(challengeId, stage.id),
    refetchInterval: (query) =>
      query.state.data?.data?.sync_state === 'PACKAGING' ? PACKAGING_POLL_MS : false,
  });
  const compute = data?.data;
  const { data: imagesResponse } = useQuery({
    queryKey: ['workspace-images', challengeId],
    queryFn: () => EnvironmentService.getWorkspaceImages(challengeId),
  });
  const images = imagesResponse?.ok ? imagesResponse.data?.images || [] : undefined;
  const imagesFailed = Boolean(imagesResponse && !imagesResponse.ok);
  const defaultImageId =
    images?.find((image) => image.default)?.image_id || images?.[0]?.image_id || '';
  const [form, setForm] = useState(() => toForm(null));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (compute) setForm(toForm(compute)); // eslint-disable-line react-hooks/set-state-in-effect
  }, [compute]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey });
    queryClient.invalidateQueries({ queryKey: ['admin-challenges'] });
    queryClient.invalidateQueries({ queryKey: ['challenges'] });
  };

  const save = async () => {
    if (form.published && !compute?.published) {
      const ok = await confirm({
        title: t('admin.compute.publish_confirm_title'),
        message: t('admin.compute.publish_confirm'),
      });
      if (!ok) return;
    }
    setSaving(true);
    const body = toBody({ ...form, image_id: form.image_id || defaultImageId });
    const res = await EnvironmentService.putStageCompute(challengeId, stage.id, body);
    setSaving(false);
    refresh();
    if (!res.ok) {
      showToast(t(`api.${res.data?.code}`, res.data?.error || ''), 'rose');
      return;
    }
    showToast(t('admin.compute.saved'), 'emerald');
  };

  const retrySync = async () => {
    const res = await EnvironmentService.syncStageCompute(challengeId, stage.id);
    refresh();
    showToast(
      res.ok ? t('admin.compute.synced') : t(`api.${res.data?.code}`, res.data?.error || ''),
      res.ok ? 'emerald' : 'rose',
    );
  };

  const locked = Boolean(compute?.published);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const stageTasks = (tasks || []).filter((task) => task.stage_id === stage.id);

  return (
    <div
      className="mt-6 p-5 bg-slate-900/40 border border-white/5 rounded-xl flex flex-col gap-4"
      data-testid="stage-compute-panel"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-white">{t('admin.compute.title')}</h3>
        {compute && (
          <span className="text-xs text-slate-400">
            {t('admin.compute.sync_state', { state: compute.sync_state })}
            {compute.readiness?.status ? ` · ${compute.readiness.status}` : ''}
          </span>
        )}
      </div>
      <ToggleField
        id={`compute-enabled-${stage.id}`}
        label={t('admin.compute.enabled')}
        checked={form.enabled}
        disabled={locked}
        onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
      />
      {form.enabled && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <SelectField
              label={t('admin.compute.kind')}
              value={form.compute_kind}
              onChange={(value) => setForm({ ...form, compute_kind: value })}
              options={[
                { value: 'CPU', label: 'CPU' },
                { value: 'GPU', label: 'GPU' },
              ]}
            />
            <InputField
              label={t('admin.compute.cpu_cores')}
              type="number"
              value={form.cpu_cores}
              onChange={set('cpu_cores')}
              disabled={locked}
            />
            <InputField
              label={t('admin.compute.memory_gib')}
              type="number"
              value={form.memory_gib}
              onChange={set('memory_gib')}
              disabled={locked}
            />
            <InputField
              label={t('admin.compute.disk_gib')}
              type="number"
              value={form.disk_gib}
              onChange={set('disk_gib')}
              disabled={locked}
            />
            <InputField
              label={t('admin.compute.max_attendance')}
              type="number"
              value={form.max_attendance}
              onChange={set('max_attendance')}
              disabled={locked}
            />
            <InputField
              label={t('admin.compute.retention_days')}
              type="number"
              value={form.retention_days}
              onChange={set('retention_days')}
              disabled={locked}
            />
          </div>
          {form.compute_kind === 'GPU' && (
            <InputField
              label={t('admin.compute.gpu_type')}
              value={form.gpu_type || ''}
              onChange={set('gpu_type')}
              disabled={locked}
            />
          )}
          <WorkspaceImagePicker
            images={images}
            loadFailed={imagesFailed}
            value={form.image_id || (locked ? '' : defaultImageId)}
            onChange={(value) => setForm({ ...form, image_id: value })}
            disabled={locked}
          />
          {compute?.enabled && <PackageStatus compute={compute} />}
          <ToggleField
            id={`compute-published-${stage.id}`}
            label={t('admin.compute.published')}
            checked={form.published}
            disabled={locked}
            onChange={(e) => setForm({ ...form, published: e.target.checked })}
          />
          {locked && <p className="text-xs text-amber-400">{t('admin.compute.locked_hint')}</p>}
        </>
      )}
      <div className="flex gap-3">
        <Button onClick={save} isLoading={saving} disabled={locked && form.published}>
          {t('admin.compute.save')}
        </Button>
        {compute?.enabled && compute?.sync_state === 'FAILED' && (
          <Button variant="secondary" onClick={retrySync}>
            {t('admin.compute.retry_sync')}
          </Button>
        )}
      </div>
      {form.enabled && stageTasks.length > 0 && (
        <div className="flex flex-col gap-3 pt-3 border-t border-white/5">
          <h4 className="text-xs font-bold text-slate-300">{t('admin.compute.task_paths')}</h4>
          {stageTasks.map((task) => (
            <TaskPaths
              key={task.id}
              task={task}
              folder={compute?.task_folders?.[task.id] || 'task1'}
              onSaved={refresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}
