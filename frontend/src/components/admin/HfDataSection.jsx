import React from 'react';
import { useTranslation } from 'react-i18next';
import { Database, FileArchive, Trash2, X } from 'lucide-react';
import Button from '../ui/Button';
import FileUploader from '../ui/FileUploader';
import Notice from '../ui/Notice';
import { formatBytes } from '../../utils/formatUnits';

// Shell commands stay untranslated; the text around them is in the locale files
const HINT_STEPS = [
  ['admin.tasks.hf.hint_models', 'hf download <org>/<name> --local-dir models/<org>/<name>'],
  [
    'admin.tasks.hf.hint_datasets',
    'hf download <org>/<name> --repo-type dataset --local-dir datasets/<org>/<name>',
  ],
  ['admin.tasks.hf.hint_zip', 'zip -r hf-data.zip models datasets'],
];

/**
 * The task's Hugging Face ZIP: what is stored and the file Save sends to the upload list.
 *
 * @param {{
 *   task?: any,
 *   file?: File | null,
 *   onFileChange?: (file: File | null) => void,
 *   onRemove?: () => void,
 *   removing?: boolean,
 *   locked?: boolean,
 *   busy?: boolean,
 * }} props
 */
export default function HfDataSection({
  task = null,
  file = null,
  onFileChange = () => {},
  onRemove = () => {},
  removing = false,
  locked = false,
  busy = false,
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language || 'en';
  const folders = Array.isArray(task?.hf_folders) ? task.hf_folders : [];
  const stored = Boolean(task?.hf_zip_sha256) || folders.length > 0;
  const skipped = Number(task?.hf_skipped_count) || 0;

  const facts = [
    task?.hf_unpacked_bytes != null && formatBytes(task.hf_unpacked_bytes, locale),
    task?.hf_file_count != null && t('admin.tasks.hf.file_count', { count: task.hf_file_count }),
    skipped > 0 && t('admin.tasks.hf.skipped', { count: skipped }),
  ].filter(Boolean);

  return (
    <div
      className="flex flex-col gap-4 bg-slate-900/30 p-6 rounded-2xl border border-white/5"
      data-testid="hf-data"
    >
      <div className="flex items-center gap-3">
        <div className="bg-amber-500/20 p-2 rounded-lg">
          <Database className="w-5 h-5 text-amber-400" aria-hidden="true" />
        </div>
        <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider">
          {t('admin.tasks.hf.title')}
        </h3>
      </div>
      <p className="text-xs text-slate-400">{t('admin.tasks.hf.desc')}</p>

      {task?.hf_zip_not_imported && (
        <Notice tone="warning" role="status">
          {t('admin.tasks.hf.not_imported')}
        </Notice>
      )}

      {stored ? (
        <div
          className="flex flex-col gap-3 p-4 bg-slate-950 border border-white/5 rounded-lg text-xs"
          data-testid="hf-current"
        >
          <ul className="flex flex-col gap-1">
            {folders.map((folder) => (
              <li key={folder} className="font-mono text-slate-200 break-all">
                {folder}/
              </li>
            ))}
          </ul>
          {facts.length > 0 && <p className="text-slate-400">{facts.join(' · ')}</p>}
          {task?.hf_zip_sha256 && (
            <p className="text-slate-500 font-mono" title={task.hf_zip_sha256}>
              {t('admin.tasks.hf.sha256', { sha: task.hf_zip_sha256.slice(0, 12) })}
            </p>
          )}
          {/* While uploads run, the stored ZIP may be the one being replaced */}
          {!locked && !busy && (
            <div>
              <Button variant="secondary" onClick={onRemove} isLoading={removing}>
                <Trash2 size={14} aria-hidden="true" />
                {t('admin.tasks.hf.remove')}
              </Button>
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs text-slate-500 italic">{t('admin.tasks.hf.empty')}</p>
      )}

      {locked ? (
        <Notice tone="info">{t('admin.tasks.public_files_locked')}</Notice>
      ) : (
        <>
          <FileUploader
            files={file ? [file] : []}
            onChange={(next) => {
              const list = typeof next === 'function' ? next(file ? [file] : []) : next;
              onFileChange(list[0] || null);
            }}
            accept=".zip"
            label={t(stored ? 'admin.tasks.hf.replace_label' : 'admin.tasks.hf.upload_label')}
            hideFileList
          />
          {file && (
            <div
              className="flex items-center justify-between gap-2 p-3 bg-slate-950 border border-emerald-500/15 rounded-lg text-xs"
              data-testid="hf-picked"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <FileArchive size={16} className="text-emerald-400 shrink-0" aria-hidden="true" />
                <span className="truncate font-mono text-slate-200">{file.name}</span>
                <span className="text-slate-500 text-[10px] shrink-0">
                  {formatBytes(file.size, locale)}
                </span>
              </div>
              <button
                type="button"
                onClick={() => onFileChange(null)}
                className="inline-flex items-center justify-center min-h-8 min-w-8 rounded text-slate-500 hover:text-rose-400 transition-colors"
                aria-label={t('common.remove_file', { name: file.name })}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {file && (
            <p className="text-[11px] text-slate-400">
              {t(stored ? 'admin.tasks.hf.picked_replace' : 'admin.tasks.hf.picked')}
            </p>
          )}
        </>
      )}

      <div className="flex flex-col gap-2 border-t border-white/5 pt-4 text-xs text-slate-400">
        <p className="font-semibold text-slate-300">{t('admin.tasks.hf.hint_title')}</p>
        <ol className="flex flex-col gap-2 list-decimal list-inside">
          {HINT_STEPS.map(([key, command]) => (
            <li key={key}>
              {t(key)}
              <code className="block mt-1 px-2 py-1 bg-slate-950 rounded font-mono text-[11px] text-slate-200 break-all">
                {command}
              </code>
            </li>
          ))}
        </ol>
        <p>{t('admin.tasks.hf.hint_rules')}</p>
      </div>
    </div>
  );
}
