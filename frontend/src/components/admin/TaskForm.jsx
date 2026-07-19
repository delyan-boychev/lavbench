import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation, Trans } from 'react-i18next';
import InputField from '../ui/InputField';
import Button from '../ui/Button';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';
import FileUploader from '../ui/FileUploader';
import TabScrollContainer from '../ui/TabScrollContainer';
import { Pencil, BarChart3, Lock, Box, Folder, Plus, FileText, X } from 'lucide-react';

export default function TaskForm({
  taskForm,
  setTaskForm,
  isCreatingTask,
  editingTask,
  setEditingTask,
  setIsCreatingTask,
  handleSaveCreateTask,
  handleSaveUpdateTask,
  challenges,
  selectedChallenge,
  availableMetrics,
  formatMetricName,
  taskFiles,
  setTaskFiles,
  baselineFile,
  setBaselineFile,
  formatDateTime,
  savingTask = false,
  evaluatorScript,
  setEvaluatorScript,
  evaluatorDeleted,
  setEvaluatorDeleted,
}) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('general');

  const existingBaselineFile = useMemo(() => {
    if (!editingTask?.files) return null;
    const arr = Array.isArray(editingTask.files)
      ? editingTask.files
      : typeof editingTask.files === 'string' && editingTask.files.trim() !== ''
        ? JSON.parse(editingTask.files)
        : [];
    return arr.find((f) => f.type === 'baseline');
  }, [editingTask]);

  const existingBaselineName = useMemo(() => {
    if (editingTask?.baseline_notebook_path) {
      return editingTask.baseline_notebook_path.split('/').pop();
    }
    if (existingBaselineFile) {
      return existingBaselineFile.filename;
    }
    return null;
  }, [editingTask, existingBaselineFile]);

  const existingFilesList = useMemo(() => {
    if (!editingTask?.files) return [];
    const arr = Array.isArray(editingTask.files)
      ? editingTask.files
      : typeof editingTask.files === 'string' && editingTask.files.trim() !== ''
        ? JSON.parse(editingTask.files)
        : [];
    const activeBaselineName = baselineFile
      ? baselineFile.name
      : !editingTask?.baselineDeleted && existingBaselineName
        ? existingBaselineName
        : null;
    return arr.filter((f) => f.type !== 'baseline' && f.filename !== activeBaselineName);
  }, [editingTask, baselineFile, existingBaselineName]);

  const newIpynbs = useMemo(() => {
    return [...(baselineFile ? [baselineFile] : []), ...taskFiles].filter((f) =>
      f.name.endsWith('.ipynb'),
    );
  }, [baselineFile, taskFiles]);

  const availableIpynbs = useMemo(() => {
    const names = newIpynbs.map((f) => f.name);
    if (existingBaselineName) {
      if (!names.includes(existingBaselineName)) {
        names.push(existingBaselineName);
      }
    }
    return names;
  }, [newIpynbs, existingBaselineName]);

  const handleSelectActiveBaseline = (name) => {
    const matchedNewFile = newIpynbs.find((f) => f.name === name);
    if (matchedNewFile) {
      setBaselineFile(matchedNewFile);
      if (editingTask) {
        setEditingTask({ ...editingTask, baselineDeleted: true });
      }
      const otherNewIpynbs = newIpynbs.filter((f) => f.name !== name);
      const nonIpynb = taskFiles.filter((f) => !f.name.endsWith('.ipynb'));
      setTaskFiles([...nonIpynb, ...otherNewIpynbs]);
    } else {
      setBaselineFile(null);
      if (editingTask) {
        setEditingTask({ ...editingTask, baselineDeleted: false });
      }
      const nonIpynb = taskFiles.filter((f) => !f.name.endsWith('.ipynb'));
      setTaskFiles([...nonIpynb, ...newIpynbs]);
    }
  };

  useEffect(() => {
    const usingExistingBaseline = existingBaselineName && !editingTask?.baselineDeleted;
    if (!baselineFile && !usingExistingBaseline) {
      const ipynbsInResources = taskFiles.filter((f) => f.name.endsWith('.ipynb'));
      if (ipynbsInResources.length > 0) {
        const promoted = ipynbsInResources[0];
        setBaselineFile(promoted);
        setTaskFiles((prev) => prev.filter((f) => f !== promoted));
      }
    }
  }, [
    baselineFile,
    taskFiles,
    existingBaselineName,
    editingTask?.baselineDeleted,
    setBaselineFile,
    setTaskFiles,
  ]);

  const evalContent = (function () {
    let metricsObj = {};
    try {
      metricsObj = JSON.parse(taskForm.metrics_config) || {};
    } catch {
      /* noop */
    }
    const columnsDef = metricsObj._columns || [];
    const metricsOnly = /** @type {Record<string, any>} */ ({ ...metricsObj });
    delete metricsOnly._columns;
    const selectedCount = Object.keys(metricsOnly).length;

    const updateMetricsConfig = (updated) => {
      setTaskForm({ ...taskForm, metrics_config: JSON.stringify(updated) });
    };

    const addColumn = () => {
      const newCol = { name: '', type: 'string', desc: '' };
      updateMetricsConfig({ ...metricsObj, _columns: [...columnsDef, newCol] });
    };

    const updateColumn = (idx, field, value) => {
      const updated = [...columnsDef];
      updated[idx] = { ...updated[idx], [field]: value };
      updateMetricsConfig({ ...metricsObj, _columns: updated });
    };

    const removeColumn = (idx) => {
      const updated = columnsDef.filter((_, i) => i !== idx);
      updateMetricsConfig({ ...metricsObj, _columns: updated });
    };

    const columnNames = columnsDef.map((c) => c.name).filter(Boolean);

    return (
      <div className="flex flex-col gap-6">
        {/* COLUMN DEFINITIONS */}
        <div className="relative z-20 flex flex-col gap-4 border border-emerald-500/20 p-5 bg-emerald-950/10 rounded-xl">
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-bold text-emerald-300">
              {t('admin.tasks.column_definitions')}
            </h3>
            <button
              type="button"
              onClick={addColumn}
              className="text-xs font-medium text-emerald-300 hover:text-emerald-200 bg-emerald-500/10 hover:bg-emerald-500/20 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Plus size={14} />
              {t('admin.tasks.add_column')}
            </button>
          </div>
          <p className="text-xs text-slate-400">
            <Trans
              i18nKey="admin.tasks.column_definitions_desc"
              components={{ code: <code className="text-emerald-300" /> }}
            />
          </p>

          {columnsDef.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-white/5">
              <table className="w-full text-left text-sm text-slate-300">
                <thead className="bg-slate-900/80 text-xs uppercase text-slate-400">
                  <tr>
                    <th className="px-4 py-3 rounded-tl-lg">{t('admin.tasks.column_name')}</th>
                    <th className="px-4 py-3">{t('admin.tasks.column_type')}</th>
                    <th className="px-4 py-3">{t('admin.tasks.column_description')}</th>
                    <th className="px-4 py-3 rounded-tr-lg text-right">
                      {t('admin.tasks.remove')}
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-slate-950/50 divide-y divide-white/5">
                  {columnsDef.map((col, idx) => (
                    <tr key={idx} className="hover:bg-slate-900/50 transition-colors">
                      <td className="px-4 py-3">
                        <input
                          type="text"
                          placeholder={t('admin.tasks.column_name_placeholder')}
                          value={col.name}
                          onChange={(e) => updateColumn(idx, 'name', e.target.value)}
                          className="w-28 text-xs bg-slate-900 border border-white/10 rounded-md text-slate-200 py-1.5 px-2 focus:outline-none focus:ring-1 focus:ring-emerald-500 placeholder-slate-600"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <SelectField
                          options={['integer', 'float', 'string', 'binary', 'list', 'struct'].map(
                            (t) => ({ value: t, label: t }),
                          )}
                          value={col.type}
                          onChange={(val) => updateColumn(idx, 'type', val)}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <input
                          type="text"
                          placeholder={t('admin.tasks.column_desc_placeholder')}
                          value={col.desc}
                          onChange={(e) => updateColumn(idx, 'desc', e.target.value)}
                          className="w-36 text-xs bg-slate-900 border border-white/10 rounded-md text-slate-200 py-1.5 px-2 focus:outline-none focus:ring-1 focus:ring-emerald-500 placeholder-slate-600"
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => removeColumn(idx)}
                          className="text-red-400 hover:text-red-300 hover:bg-red-400/10 p-1.5 rounded-lg transition-colors"
                        >
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            className="h-4 w-4"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth="2"
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                            />
                          </svg>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-xs text-slate-500 italic p-3 bg-slate-900/30 rounded-lg border border-dashed border-white/5 text-center">
              {t('admin.tasks.no_columns_defined')}
            </div>
          )}
        </div>

        {/* METRICS CONFIGURATION */}
        <div className="relative z-10 flex flex-col gap-4 border border-indigo-500/20 p-5 bg-indigo-950/10 rounded-xl">
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-bold text-indigo-300">
              {t('admin.tasks.evaluation_metrics')}
            </h3>
            <span className="bg-indigo-600/30 text-indigo-300 text-xs py-1 px-2.5 rounded-full font-medium">
              {t('admin.tasks.metrics_selected_count', { count: selectedCount })}
            </span>
          </div>

          {selectedCount >= 10 && (
            <div className="text-xs text-amber-500 font-medium bg-amber-500/10 p-2 rounded border border-amber-500/20">
              {t('admin.tasks.maximum_metric_limit')}
            </div>
          )}

          <div className="flex gap-2 w-full">
            <SelectField
              options={Object.keys(availableMetrics)
                .filter((m) => !metricsOnly[m])
                .sort()
                .map((m) => ({ value: m, label: formatMetricName(m) }))}
              value=""
              onChange={(mName) => {
                if (mName && !metricsOnly[mName]) {
                  let updatedObj = { ...metricsObj };
                  const schema = availableMetrics[mName] || {};
                  let defaultOpts = { column: columnNames[0] || '' };
                  if (schema.average) defaultOpts.average = schema.average[0];
                  if (schema.rouge_type) defaultOpts.rouge_type = schema.rouge_type[0];
                  if (schema.k) defaultOpts.k = parseInt(schema.k[0]);
                  if (schema.threshold) defaultOpts.threshold = parseFloat(schema.threshold[0]);
                  if (schema.beta) defaultOpts.beta = parseInt(schema.beta[0]);
                  if (schema.shape) defaultOpts.shape = '0';
                  if (schema.multioutput) defaultOpts.multioutput = schema.multioutput[0];
                  updatedObj[mName] = { weight: 1.0, options: defaultOpts };
                  updateMetricsConfig(updatedObj);
                }
              }}
              placeholder={t('admin.tasks.add_eval_metric')}
              disabled={selectedCount >= 10}
            />
          </div>

          {selectedCount > 0 && (
            <div className="overflow-x-auto rounded-lg border border-white/5">
              <table className="w-full text-left text-sm text-slate-300">
                <thead className="bg-slate-900/80 text-xs uppercase text-slate-400">
                  <tr>
                    <th className="px-4 py-3 rounded-tl-lg">{t('admin.tasks.metric')}</th>
                    <th className="px-4 py-3">{t('admin.tasks.weight')}</th>
                    <th className="px-4 py-3">{t('admin.tasks.column_mapping')}</th>
                    <th className="px-4 py-3">{t('admin.tasks.parameters')}</th>
                    <th className="px-4 py-3 rounded-tr-lg text-right">
                      {t('admin.tasks.remove')}
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-slate-950/50 divide-y divide-white/5">
                  {Object.keys(metricsOnly).map((mName) => {
                    const currentWeight =
                      metricsOnly[mName].weight !== undefined ? metricsOnly[mName].weight : 1.0;
                    const schema = availableMetrics[mName] || {};
                    const opts = metricsOnly[mName].options || {};

                    return (
                      <tr key={mName} className="hover:bg-slate-900/50 transition-colors">
                        <td className="px-4 py-3 font-medium text-slate-200">
                          {formatMetricName(mName)}
                        </td>
                        <td className="px-4 py-3">
                          <input
                            type="number"
                            step="0.1"
                            min="0"
                            value={currentWeight}
                            onChange={(e) => {
                              let updatedObj = { ...metricsObj };
                              updatedObj[mName].weight = parseFloat(e.target.value) || 0;
                              updateMetricsConfig(updatedObj);
                            }}
                            className="w-16 text-center text-xs bg-slate-900 border border-white/10 rounded-md text-slate-200 py-1 px-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          />
                        </td>
                        <td className="px-4 py-3">
                          <SelectField
                            options={columnNames.map((cn) => ({ value: cn, label: cn }))}
                            value={opts.column || ''}
                            onChange={(val) => {
                              let updatedObj = { ...metricsObj };
                              updatedObj[mName].options = { ...opts, column: val };
                              updateMetricsConfig(updatedObj);
                            }}
                            placeholder={t('admin.tasks.no_columns_option')}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-2">
                            {Object.keys(schema).map((param) => {
                              if (schema[param] === 'string') {
                                return (
                                  <div
                                    key={param}
                                    className="flex items-center gap-1.5 bg-slate-900/80 p-1 rounded border border-white/5"
                                  >
                                    <span className="text-[10px] text-slate-400 capitalize">
                                      {param}:
                                    </span>
                                    <input
                                      type="text"
                                      placeholder="0"
                                      value={opts[param] || ''}
                                      onChange={(e) => {
                                        let updatedObj = { ...metricsObj };
                                        updatedObj[mName].options = {
                                          ...opts,
                                          [param]: e.target.value,
                                        };
                                        updateMetricsConfig(updatedObj);
                                      }}
                                      className="w-16 text-center text-[11px] bg-slate-950 border border-transparent rounded text-slate-200 py-0.5 focus:border-indigo-500/50 focus:outline-none"
                                    />
                                  </div>
                                );
                              } else if (Array.isArray(schema[param])) {
                                return (
                                  <div
                                    key={param}
                                    className="flex items-center gap-1.5 bg-slate-900/80 p-1 rounded border border-white/5"
                                  >
                                    <span className="text-[10px] text-slate-400 capitalize">
                                      {param.replace('_', ' ')}:
                                    </span>
                                    <SelectField
                                      options={schema[param].map((val) => ({
                                        value: val.toString(),
                                        label: val.toString(),
                                      }))}
                                      value={(opts[param] || schema[param][0]).toString()}
                                      onChange={(val) => {
                                        let updatedObj = { ...metricsObj };
                                        updatedObj[mName].options = {
                                          ...opts,
                                          [param]: val,
                                        };
                                        updateMetricsConfig(updatedObj);
                                      }}
                                    />
                                  </div>
                                );
                              }
                              return null;
                            })}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            className="text-red-400 hover:text-red-300 hover:bg-red-400/10 p-1.5 rounded-lg transition-colors"
                            title={t('admin.tasks.remove_metric_title')}
                            onClick={() => {
                              let updatedObj = { ...metricsObj };
                              delete updatedObj[mName];
                              updateMetricsConfig(updatedObj);
                            }}
                          >
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              className="h-4 w-4"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth="2"
                                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                              />
                            </svg>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* FORMAT VISUALIZER */}
          {columnsDef.length > 0 && (
            <div className="flex flex-col gap-4 border border-white/10 p-5 bg-slate-900/40 rounded-xl">
              <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider">
                {t('admin.tasks.parquet_preview')}
              </h3>
              <p className="text-xs text-slate-400">{t('admin.tasks.parquet_preview_desc')}</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* submission.parquet */}
                <div className="rounded-xl border border-indigo-500/20 bg-slate-950/60 overflow-hidden">
                  <div className="bg-indigo-500/10 px-4 py-3 border-b border-indigo-500/20">
                    <span className="text-sm font-semibold text-indigo-300">
                      submission.parquet
                    </span>
                    <span className="text-[10px] text-slate-500 ml-3">
                      {t('admin.tasks.produced_by_notebook')}
                    </span>
                  </div>
                  <div className="p-0">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-900/80 border-b border-white/5">
                        <tr>
                          <th className="px-4 py-2 text-slate-400 font-medium">
                            {t('admin.tasks.column_name')}
                          </th>
                          <th className="px-4 py-2 text-slate-400 font-medium">
                            {t('admin.tasks.column_type')}
                          </th>
                          <th className="px-4 py-2 text-slate-400 font-medium">
                            {t('admin.tasks.used_by')}
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {columnsDef.map((col, idx) => {
                          const usedBy = Object.keys(metricsOnly).filter((mName) => {
                            const mOpts = metricsOnly[mName].options || {};
                            return mOpts.column === col.name;
                          });
                          return (
                            <tr key={idx} className="hover:bg-slate-900/50 transition-colors">
                              <td className="px-4 py-2.5">
                                <code className="text-emerald-300 font-semibold">{col.name}</code>
                              </td>
                              <td className="px-4 py-2.5 text-slate-400">{col.type}</td>
                              <td className="px-4 py-2.5">
                                {usedBy.length > 0 ? (
                                  <div className="flex flex-wrap gap-1">
                                    {usedBy.map((m) => (
                                      <span
                                        key={m}
                                        className="text-[10px] bg-indigo-500/15 text-indigo-300 px-1.5 py-0.5 rounded"
                                      >
                                        {formatMetricName(m)}
                                      </span>
                                    ))}
                                  </div>
                                ) : (
                                  <span className="text-slate-600 italic">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* labels.parquet */}
                <div className="rounded-xl border border-emerald-500/20 bg-slate-950/60 overflow-hidden">
                  <div className="bg-emerald-500/10 px-4 py-3 border-b border-emerald-500/20">
                    <span className="text-sm font-semibold text-emerald-300">labels.parquet</span>
                    <span className="text-[10px] text-slate-500 ml-3">
                      {t('admin.tasks.uploaded_by_admin')}
                    </span>
                  </div>
                  <div className="p-0">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-900/80 border-b border-white/5">
                        <tr>
                          <th className="px-4 py-2 text-slate-400 font-medium">
                            {t('admin.tasks.column_name')}
                          </th>
                          <th className="px-4 py-2 text-slate-400 font-medium">
                            {t('admin.tasks.column_type')}
                          </th>
                          <th className="px-4 py-2 text-slate-400 font-medium">
                            {t('admin.tasks.role')}
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {columnsDef.map((col, idx) => (
                          <tr key={idx} className="hover:bg-slate-900/50 transition-colors">
                            <td className="px-4 py-2.5">
                              <code className="text-emerald-300 font-semibold">{col.name}</code>
                            </td>
                            <td className="px-4 py-2.5 text-slate-400">{col.type}</td>
                            <td className="px-4 py-2.5">
                              <span className="text-slate-400">
                                {col.name === 'id'
                                  ? t('admin.tasks.join_key')
                                  : t('admin.tasks.ground_truth')}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  })();

  const TABS = [
    { id: 'general', label: t('admin.tasks.tabs.general'), Icon: Pencil },
    { id: 'evaluation', label: t('admin.tasks.tabs.evaluation'), Icon: BarChart3 },
    { id: 'sandbox', label: t('admin.tasks.tabs.sandbox'), Icon: Lock },
    { id: 'environment', label: t('admin.tasks.tabs.environment'), Icon: Box },
    { id: 'files', label: t('admin.tasks.tabs.files'), Icon: Folder },
  ];

  return (
    <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl shadow-2xl animate-fadein">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-bold text-white tracking-tight">
          {isCreatingTask
            ? t('admin.tasks.create_task_under', { title: selectedChallenge?.title })
            : t('admin.tasks.edit_task', { title: editingTask?.title })}
        </h2>
      </div>

      <div className="mb-6">
        <TabScrollContainer>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 whitespace-nowrap ${
                activeTab === tab.id
                  ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 shadow-inner'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent'
              }`}
            >
              <span className={activeTab === tab.id ? 'text-indigo-400' : 'text-slate-500'}>
                <tab.Icon />
              </span>
              {tab.label}
            </button>
          ))}
        </TabScrollContainer>
      </div>

      <form
        onSubmit={isCreatingTask ? handleSaveCreateTask : handleSaveUpdateTask}
        className="flex flex-col gap-8 min-h-[400px]"
      >
        {/* TAB: GENERAL */}
        {activeTab === 'general' && (
          <div className="animate-fadein flex flex-col gap-5">
            <InputField
              label={t('admin.tasks.task_title')}
              value={taskForm.title}
              onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })}
              required
            />

            <SelectField
              label={t('admin.tasks.stage_optional')}
              value={taskForm.stage_id}
              onChange={(val) => setTaskForm({ ...taskForm, stage_id: val })}
              options={[
                { value: '', label: t('admin.tasks.stage_none') },
                ...(
                  challenges.find(
                    (c) =>
                      c.id === (editingTask ? editingTask.challenge_id : selectedChallenge?.id),
                  )?.stages || []
                ).map((st) => {
                  const challenge = challenges.find(
                    (c) =>
                      c.id === (editingTask ? editingTask.challenge_id : selectedChallenge?.id),
                  );
                  return {
                    value: st.id.toString(),
                    label: t('admin.tasks.stage_option_label', {
                      number: st.stage_number,
                      title: st.title,
                      start: formatDateTime(st.start_time, challenge?.timezone),
                      end: formatDateTime(st.end_time, challenge?.timezone),
                    }),
                  };
                }),
              ]}
            />

            <InputField
              multiline
              label={t('admin.tasks.description_markdown')}
              value={taskForm.description}
              onChange={(e) => setTaskForm({ ...taskForm, description: e.target.value })}
              rows={6}
              required
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-4 pt-6 border-t border-white/5">
              <InputField
                label={t('admin.tasks.max_submissions')}
                type="number"
                value={taskForm.max_submissions_per_period}
                onChange={(e) =>
                  setTaskForm({ ...taskForm, max_submissions_per_period: e.target.value })
                }
                placeholder={t('admin.tasks.max_submissions_placeholder')}
              />
              <InputField
                label={t('admin.tasks.submission_period_hours')}
                type="number"
                value={taskForm.submission_period_hours}
                onChange={(e) =>
                  setTaskForm({ ...taskForm, submission_period_hours: e.target.value })
                }
                placeholder={t('admin.tasks.submission_period_placeholder')}
              />
            </div>
          </div>
        )}

        {/* TAB: EVALUATION */}
        {activeTab === 'evaluation' && (
          <div className="animate-fadein flex flex-col gap-6">
            <div className="grid bg-slate-900/40 p-5 rounded-xl border border-white/5">
              <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
                    {t('admin.tasks.public_eval_split_percentage', {
                      percentage: taskForm.public_eval_percentage,
                    })}
                  </label>
                  <span className="text-xs font-bold text-indigo-400">
                    {taskForm.public_eval_percentage}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={taskForm.public_eval_percentage}
                  onChange={(e) =>
                    setTaskForm({
                      ...taskForm,
                      public_eval_percentage: parseInt(e.target.value) || 0,
                    })
                  }
                  className="w-full accent-indigo-500 h-2 bg-slate-950 rounded-lg cursor-pointer border border-white/5 mt-2"
                />
              </div>
            </div>

            {/* CUSTOM EVALUATOR SCRIPT */}
            <div className="flex flex-col gap-4 border border-violet-500/20 p-5 bg-violet-950/10 rounded-xl">
              <div className="flex justify-between items-center">
                <h3 className="text-sm font-bold text-violet-300">
                  {t('admin.tasks.custom_evaluator_script')}
                </h3>
              </div>
              <p className="text-xs text-slate-400">
                {t('admin.tasks.custom_evaluator_desc')}
              </p>

              {/* Existing Evaluator (editing) */}
              {editingTask?.evaluator_script_path && !evaluatorScript && !evaluatorDeleted && (
                <div className="flex items-center justify-between p-3 bg-slate-950 border border-violet-500/15 rounded-lg text-xs">
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <FileText size={16} className="text-violet-400 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <span className="truncate text-slate-200 font-semibold font-mono block">
                        evaluator.py
                      </span>
                      {editingTask.evaluator_metric_name && (
                        <span className="text-violet-400 text-[10px] font-mono">
                          {editingTask.evaluator_metric_name}
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setEvaluatorDeleted(true)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-400/10 p-1.5 rounded-lg transition-colors ml-2"
                  >
                    <X size={14} />
                  </button>
                </div>
              )}

              {/* Replace / Upload */}
              {(!editingTask?.evaluator_script_path || evaluatorDeleted) && !evaluatorScript && (
                <div className="border-2 border-dashed border-slate-700/50 rounded-xl p-6 text-center hover:border-violet-500/30 transition-colors">
                  <input
                    type="file"
                    accept=".py"
                    id="evaluator-script-upload"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        setEvaluatorScript(file);
                        setEvaluatorDeleted(false);
                      }
                    }}
                  />
                  <label
                    htmlFor="evaluator-script-upload"
                    className="cursor-pointer flex flex-col items-center gap-2"
                  >
                    <FileText size={24} className="text-slate-500" />
                    <span className="text-xs text-slate-400 font-medium">
                      {t('admin.tasks.custom_evaluator_upload_label')}
                    </span>
                    <span className="text-[10px] text-slate-500">.py</span>
                  </label>
                </div>
              )}

              {/* Newly selected evaluator script */}
              {evaluatorScript && (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between p-3 bg-slate-950 border border-emerald-500/15 rounded-lg text-xs">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <FileText size={16} className="text-emerald-400 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <span className="truncate text-slate-200 font-semibold font-mono block">
                          {evaluatorScript.name}
                        </span>
                        <span className="text-slate-500 text-[10px]">
                          {(evaluatorScript.size / 1024).toFixed(1)} KB
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setEvaluatorScript(null)}
                      className="text-slate-500 hover:text-rose-400 transition-colors ml-2"
                    >
                      <X size={14} />
                    </button>
                  </div>
                  {/* Read file content preview */}
                  <ScriptPreview file={evaluatorScript} />
                </div>
              )}
            </div>

            {evalContent}
          </div>
        )}

        {/* TAB: SANDBOX */}
        {activeTab === 'sandbox' && (
          <div className="animate-fadein flex flex-col gap-8">
            <div className="flex flex-col gap-4">
              <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider mb-2">
                {t('admin.tasks.resource_limits')}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                <InputField
                  label={t('admin.tasks.override_ram')}
                  type="number"
                  value={taskForm.ram_limit_mb}
                  onChange={(e) => setTaskForm({ ...taskForm, ram_limit_mb: e.target.value })}
                  placeholder={t('admin.tasks.ram_limit_placeholder')}
                />
                <InputField
                  label={t('admin.tasks.override_timeout')}
                  type="number"
                  value={taskForm.time_limit_sec}
                  onChange={(e) => setTaskForm({ ...taskForm, time_limit_sec: e.target.value })}
                  placeholder={t('admin.tasks.time_limit_placeholder')}
                />
                <div className="flex items-center h-full pt-5">
                  <div className="bg-slate-900/50 p-3 w-full rounded-xl border border-white/5 h-full flex items-center">
                    <ToggleField
                      label={t('admin.tasks.requires_gpu_worker_node')}
                      id="task-gpu-req"
                      checked={taskForm.gpu_required}
                      onChange={(e) => setTaskForm({ ...taskForm, gpu_required: e.target.checked })}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="flex flex-col gap-4 border-t border-white/5 pt-6">
              <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider mb-2">
                {t('admin.tasks.ast_security_rules')}
              </h3>
              <div className="flex flex-col md:flex-row gap-5 mb-4">
                <div className="bg-slate-900/50 p-4 w-full rounded-xl border border-white/5">
                  <ToggleField
                    label={t('admin.tasks.ban_magic_commands')}
                    id="rule-magic"
                    checked={taskForm.ban_magic_commands}
                    onChange={(e) =>
                      setTaskForm({ ...taskForm, ban_magic_commands: e.target.checked })
                    }
                  />
                  <p className="text-[11px] text-slate-500 mt-2">
                    {t('admin.tasks.ban_magic_desc')}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <InputField
                  label={t('admin.tasks.banned_libraries')}
                  value={taskForm.banned_imports}
                  onChange={(e) => setTaskForm({ ...taskForm, banned_imports: e.target.value })}
                  placeholder={t('admin.tasks.banned_libraries_placeholder')}
                />
                <InputField
                  label={t('admin.tasks.whitelisted_libraries_label')}
                  value={taskForm.whitelisted_imports}
                  onChange={(e) =>
                    setTaskForm({ ...taskForm, whitelisted_imports: e.target.value })
                  }
                  placeholder={t('admin.tasks.whitelisted_libraries_placeholder')}
                />
              </div>
            </div>
          </div>
        )}

        {/* TAB: ENVIRONMENT */}
        {activeTab === 'environment' && (
          <div className="animate-fadein flex flex-col gap-8">
            <div className="flex flex-col gap-4 bg-slate-900/30 p-6 rounded-2xl border border-white/5">
              <div className="flex items-center gap-3 mb-2">
                <div className="bg-blue-500/20 p-2 rounded-lg">
                  <svg
                    className="w-5 h-5 text-blue-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                    />
                  </svg>
                </div>
                <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider">
                  {t('admin.tasks.docker_sandbox')}
                </h3>
              </div>
              <p className="text-xs text-slate-400 mb-4">{t('admin.tasks.docker_sandbox_desc')}</p>

              <InputField
                label={t('admin.tasks.base_image')}
                value={taskForm.base_docker_image}
                onChange={(e) => setTaskForm({ ...taskForm, base_docker_image: e.target.value })}
                placeholder={t('admin.tasks.base_image_placeholder')}
              />
              <InputField
                label={t('admin.tasks.apt_packages')}
                value={taskForm.apt_packages}
                onChange={(e) => setTaskForm({ ...taskForm, apt_packages: e.target.value })}
                placeholder={t('admin.tasks.apt_packages_placeholder')}
              />
              <InputField
                multiline
                label={t('admin.tasks.pip_requirements')}
                value={taskForm.pip_requirements}
                onChange={(e) => setTaskForm({ ...taskForm, pip_requirements: e.target.value })}
                placeholder={t('admin.tasks.pip_requirements_placeholder')}
                rows={4}
              />
            </div>

            <div className="flex flex-col gap-4 bg-amber-900/10 p-6 rounded-2xl border border-amber-500/20">
              <div className="flex items-center gap-3 mb-2">
                <div className="bg-amber-500/20 p-2 rounded-lg">
                  <svg
                    className="w-5 h-5 text-amber-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M13 10V3L4 14h7v7l9-11h-7z"
                    />
                  </svg>
                </div>
                <h3 className="text-sm font-bold text-amber-200 uppercase tracking-wider">
                  {t('admin.tasks.hf_integrations')}
                </h3>
              </div>
              <p className="text-xs text-amber-400/70 mb-4">
                {t('admin.tasks.hf_integrations_desc')}
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <InputField
                  label={t('admin.tasks.hf_datasets_label')}
                  value={taskForm.hf_datasets_raw}
                  onChange={(e) => setTaskForm({ ...taskForm, hf_datasets_raw: e.target.value })}
                  placeholder={t('admin.tasks.hf_datasets_placeholder')}
                />
                <InputField
                  label={t('admin.tasks.hf_models_label')}
                  value={taskForm.hf_models_raw}
                  onChange={(e) => setTaskForm({ ...taskForm, hf_models_raw: e.target.value })}
                  placeholder={t('admin.tasks.hf_models_placeholder')}
                />
              </div>
              <InputField
                label={t('admin.tasks.hf_api_key')}
                type="password"
                value={taskForm.hf_api_key}
                onChange={(e) => setTaskForm({ ...taskForm, hf_api_key: e.target.value })}
                placeholder={t('admin.tasks.hf_api_key_placeholder')}
              />
            </div>
          </div>
        )}

        {/* TAB: FILES */}
        {activeTab === 'files' && (
          <div className="animate-fadein flex flex-col gap-8">
            <div className="bg-slate-900/40 p-6 rounded-2xl border border-white/5">
              <FileUploader
                files={[...(baselineFile ? [baselineFile] : []), ...taskFiles]}
                onChange={(newFilesOrFn) => {
                  const resolvedFiles =
                    typeof newFilesOrFn === 'function'
                      ? newFilesOrFn([...(baselineFile ? [baselineFile] : []), ...taskFiles])
                      : newFilesOrFn;

                  const ipynb = resolvedFiles.filter((f) => f.name.endsWith('.ipynb'));
                  if (ipynb.length > 0) {
                    const chosen = ipynb[ipynb.length - 1];
                    setBaselineFile(chosen);
                    if (editingTask) {
                      setEditingTask({ ...editingTask, baselineDeleted: false });
                    }
                    const otherIpynbs = ipynb.slice(0, ipynb.length - 1);
                    const nonIpynb = resolvedFiles.filter((f) => !f.name.endsWith('.ipynb'));
                    setTaskFiles([...nonIpynb, ...otherIpynbs]);
                  } else {
                    setBaselineFile(null);
                    setTaskFiles(resolvedFiles);
                  }
                }}
                multiple
                accept=".parquet,.csv,.py,.txt,.json,.jsonl,.tsv,.pkl,.ipynb"
                label={t('admin.tasks.files_and_baseline')}
                description={t('admin.tasks.files_and_baseline_desc')}
                hideFileList={true}
              />
            </div>

            {/* SEPARATED FILES LIST */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* SECTION: BASELINE NOTEBOOK */}
              <div className="bg-slate-900/40 p-6 rounded-2xl border border-white/5 flex flex-col gap-4">
                <div className="flex justify-between items-center border-b border-white/5 pb-2">
                  <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider">
                    {t('admin.tasks.baseline_code')}
                  </h3>
                  {!baselineFile && (!existingBaselineName || editingTask.baselineDeleted) ? (
                    <span className="text-[10px] text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded-full border border-rose-500/20 font-bold uppercase tracking-wider">
                      {t('admin.tasks.missing_baseline')}
                    </span>
                  ) : (
                    <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 font-bold uppercase tracking-wider">
                      {t('admin.tasks.ready_badge')}
                    </span>
                  )}
                </div>

                {/* Existing Baseline */}
                {existingBaselineName && !baselineFile && (
                  <div
                    className={`flex items-center justify-between p-3 rounded-lg text-xs transition-colors ${
                      editingTask.baselineDeleted
                        ? 'bg-red-500/10 border border-red-500/20'
                        : 'bg-slate-950 border border-indigo-500/15'
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <FileText
                        size={16}
                        className={editingTask.baselineDeleted ? 'text-red-400' : 'text-indigo-400'}
                      />
                      <span
                        className={`truncate flex-1 font-mono ${
                          editingTask.baselineDeleted
                            ? 'line-through text-slate-500'
                            : 'text-indigo-300 font-semibold'
                        }`}
                      >
                        {existingBaselineName}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() =>
                        setEditingTask({
                          ...editingTask,
                          baselineDeleted: !editingTask.baselineDeleted,
                        })
                      }
                      className={`text-xs px-3 py-1.5 rounded font-bold transition-colors ml-2 ${
                        editingTask.baselineDeleted
                          ? 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                          : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                      }`}
                    >
                      {editingTask.baselineDeleted
                        ? t('admin.tasks.undo_delete')
                        : t('admin.stages.delete')}
                    </button>
                  </div>
                )}

                {/* Newly Selected Baseline */}
                {baselineFile && (
                  <div className="flex items-center justify-between p-3 bg-slate-950 border border-emerald-500/15 rounded-lg text-xs">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <FileText size={16} className="text-emerald-400" />
                      <span className="truncate flex-1 text-slate-200 font-semibold font-mono">
                        {baselineFile.name}
                      </span>
                      <span className="text-slate-500 text-[10px]">
                        {(baselineFile.size / 1024).toFixed(1)} KB
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setBaselineFile(null)}
                      className="text-slate-500 hover:text-rose-400 transition-colors ml-2"
                    >
                      <X size={14} />
                    </button>
                  </div>
                )}

                {!baselineFile && (!existingBaselineName || editingTask.baselineDeleted) && (
                  <p className="text-xs text-slate-500 italic py-2">
                    {t('admin.tasks.baseline_required_help')}
                  </p>
                )}

                {availableIpynbs.length > 1 && (
                  <div className="flex flex-col gap-2 mt-2 border-t border-white/5 pt-4">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                      {t('admin.tasks.select_active_baseline', 'Select Active Baseline Notebook')}
                    </label>
                    <div className="flex flex-col gap-2">
                      {availableIpynbs.map((name) => {
                        const isActive = baselineFile
                          ? baselineFile.name === name
                          : !editingTask?.baselineDeleted && existingBaselineName === name;
                        return (
                          <label
                            key={name}
                            className={`flex items-center gap-3 p-3 rounded-lg border text-xs cursor-pointer transition-all ${
                              isActive
                                ? 'bg-indigo-600/10 border-indigo-500/50 text-indigo-300'
                                : 'bg-slate-950 border-white/5 text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            <input
                              type="radio"
                              name="active-baseline-notebook"
                              checked={isActive}
                              onChange={() => {
                                handleSelectActiveBaseline(name);
                              }}
                              className="accent-indigo-500"
                            />
                            <span className="font-mono truncate flex-1">{name}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {/* SECTION: RESOURCE FILES */}
              <div className="bg-slate-900/40 p-6 rounded-2xl border border-white/5 flex flex-col gap-4">
                <div className="flex justify-between items-center border-b border-white/5 pb-2">
                  <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider">
                    {t('admin.tasks.ground_truth_resources')}
                  </h3>
                  {(() => {
                    const deleted = editingTask?.filesToDelete || [];
                    const activeExistingNames = existingFilesList
                      .filter((f) => !deleted.includes(f.filename))
                      .map((f) => f.filename);
                    const allResourceNames = [
                      ...taskFiles.map((f) => f.name),
                      ...activeExistingNames,
                    ];
                    const hasLabels = allResourceNames.includes('labels.parquet');
                    return !hasLabels ? (
                      <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20 font-bold uppercase tracking-wider font-mono">
                        {t('admin.tasks.missing_labels_parquet')}
                      </span>
                    ) : (
                      <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 font-bold uppercase tracking-wider">
                        {t('admin.tasks.ready_badge')}
                      </span>
                    );
                  })()}
                </div>

                {/* Existing Resource Files */}
                {existingFilesList.length > 0 && (
                  <div className="flex flex-col gap-2">
                    {(() => {
                      const deleted = editingTask?.filesToDelete || [];
                      return existingFilesList.map((f) => {
                        const isDeleted = deleted.includes(f.filename);
                        return (
                          <div
                            key={f.filename}
                            data-testid={`existing-file-${f.filename}`}
                            className={`flex items-center justify-between p-3 rounded-lg text-xs transition-colors ${
                              isDeleted
                                ? 'bg-red-500/10 border border-red-500/20'
                                : 'bg-slate-950 border border-white/5'
                            }`}
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <FileText
                                size={16}
                                className={isDeleted ? 'text-red-400' : 'text-indigo-400'}
                              />
                              <span
                                className={`truncate flex-1 font-mono ${
                                  isDeleted ? 'line-through text-slate-500' : 'text-slate-200'
                                }`}
                              >
                                {f.filename}
                              </span>
                              <span className="text-slate-500 text-[10px]">
                                {(f.size_bytes / 1024).toFixed(1)} KB
                              </span>
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                const current = editingTask.filesToDelete || [];
                                const next = current.includes(f.filename)
                                  ? current.filter((x) => x !== f.filename)
                                  : [...current, f.filename];
                                setEditingTask({ ...editingTask, filesToDelete: next });
                              }}
                              className={`text-xs px-3 py-1.5 rounded font-bold transition-colors ml-2 ${
                                isDeleted
                                  ? 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                                  : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                              }`}
                            >
                              {isDeleted ? t('admin.tasks.undo_delete') : t('admin.stages.delete')}
                            </button>
                          </div>
                        );
                      });
                    })()}
                  </div>
                )}

                {/* Newly Selected Resource Files */}
                {taskFiles.length > 0 && (
                  <div className="flex flex-col gap-2">
                    {taskFiles.map((file, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-3 bg-slate-950 border border-white/5 rounded-lg text-xs text-slate-300"
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <FileText size={16} className="text-indigo-400" />
                          <span className="truncate flex-1 font-mono text-slate-200">
                            {file.name}
                          </span>
                          <span className="text-slate-500 text-[10px]">
                            {(file.size / 1024).toFixed(1)} KB
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => setTaskFiles((prev) => prev.filter((_, i) => i !== idx))}
                          className="text-slate-500 hover:text-rose-400 transition-colors ml-2"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {taskFiles.length === 0 && existingFilesList.length === 0 && (
                  <p className="text-xs text-slate-500 italic py-2">
                    {t('admin.tasks.resources_required_help')}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="flex justify-end gap-4 border-t border-white/10 pt-6 mt-4">
          <Button
            variant="secondary"
            onClick={() => {
              setIsCreatingTask(false);
              setEditingTask(null);
            }}
            className="px-8 py-2.5"
          >
            {t('common.cancel')}
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={savingTask}
            className="px-8 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-bold shadow-lg shadow-indigo-600/20"
          >
            {savingTask
              ? t('common.loading')
              : isCreatingTask
                ? t('admin.tasks.create_task_btn')
                : t('admin.stages.save_changes_btn')}
          </Button>
        </div>
      </form>
    </div>
  );
}

function ScriptPreview({ file }) {
  const [content, setContent] = useState('');
  const [metricName, setMetricName] = useState('');

  useEffect(() => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target.result;
      if (typeof text !== 'string') return;
      setContent(text);
      const match = text.match(/^METRIC_NAME\s*=\s*["']([^"']+)["']/m);
      setMetricName(match ? match[1] : '');
    };
    reader.readAsText(file);
  }, [file]);

  if (!content) return null;

  return (
    <div className="rounded-lg border border-white/5 overflow-hidden">
      {metricName && (
        <div className="flex items-center gap-2 px-3 py-2 bg-violet-500/10 border-b border-violet-500/20">
          <span className="text-[10px] text-slate-400 uppercase tracking-wider">Metric:</span>
          <span className="text-xs font-mono font-bold text-violet-300">{metricName}</span>
        </div>
      )}
      <pre className="text-[11px] text-slate-400 leading-relaxed p-3 max-h-32 overflow-y-auto bg-slate-950/80 font-mono whitespace-pre-wrap">
        {content.length > 800 ? content.slice(0, 800) + '\n...' : content}
      </pre>
    </div>
  );
}
