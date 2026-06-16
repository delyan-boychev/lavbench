import React, { useRef, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, Upload, X } from 'lucide-react';

export default function FileUploader({
  files = [],
  onChange,
  accept,
  multiple = false,
  label,
  description = '',
  required = false,
  requiredFiles = [],
  maxFiles = 0,
  className = '',
  existingFiles = [],
  onRemoveExisting = (/** @type {string} */ _filename) => {},
}) {
  const { t } = useTranslation();
  const inputRef = useRef(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (files.length > 0 || existingFiles.length > 0) setError(false);
  }, [files, existingFiles]);

  const handleFiles = (e) => {
    const incoming = Array.from(e.target.files);
    if (multiple) {
      onChange(prev => {
        const existingNames = new Set(prev.map(f => f.name));
        existingFiles.filter(f => !f._deleted).forEach(f => existingNames.add(f.filename));
        const uniqueNew = incoming.filter(f => !existingNames.has(f.name));
        const merged = [...prev, ...uniqueNew];
        return maxFiles ? merged.slice(0, maxFiles) : merged;
      });
    } else {
      onChange(incoming.slice(0, 1));
    }
    e.target.value = '';
  };

  const removeFile = (index) => {
    onChange(prev => prev.filter((_, i) => i !== index));
  };

  const allFilenames = [
    ...files.map(f => f.name),
    ...existingFiles.filter(f => !f._deleted).map(f => f.filename),
  ];
  const missingRequired = requiredFiles.filter(name => !allFilenames.includes(name));

  const totalCount = files.length + existingFiles.filter(f => !f._deleted).length;
  const isOverLimit = maxFiles && totalCount >= maxFiles;

  const acceptedFormats = accept
    ? accept.split(',').map(s => s.trim()).join(', ')
    : t('admin.tasks.allowed_file_types');

  return (
    <div className={`flex flex-col gap-3 ${className}`} style={{ position: 'relative' }}>
      {label && (
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider">{label}</h3>
          {required && <span className="text-rose-500 text-xs font-bold">*</span>}
          {missingRequired.length > 0 && (
            <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20">
              {t('admin.tasks.missing_required_files', { files: missingRequired.join(', ') })}
            </span>
          )}
        </div>
      )}
      {description && (
        <p className="text-xs text-slate-400">{description}</p>
      )}

      {existingFiles.length > 0 && (
        <div className="flex flex-col gap-2">
          {existingFiles.map((f) => {
            const isDeleted = f._deleted;
            return (
              <div key={f.filename} className={`flex items-center justify-between p-3 rounded-lg text-xs transition-colors ${isDeleted ? 'bg-red-500/10 border border-red-500/20' : 'bg-slate-900 border border-white/5'}`}>
                <div className="flex items-center gap-2">
                  <FileText size={16} className={`flex-shrink-0 ${isDeleted ? 'text-red-400' : 'text-indigo-400'}`} />
                  <span className={`truncate flex-1 ${isDeleted ? 'line-through text-slate-500' : 'text-slate-200 font-medium'}`}>{f.filename}</span>
                  <span className="text-slate-500 text-[10px]">{(f.size_bytes / 1024).toFixed(1)} KB</span>
                </div>
                {onRemoveExisting && (
                  <button type="button" onClick={() => onRemoveExisting(f.filename)} className={`text-xs px-3 py-1.5 rounded font-bold transition-colors ${isDeleted ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'}`}>
                    {isDeleted ? t('admin.tasks.undo_delete') : t('admin.stages.delete')}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!isOverLimit && (
        <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-slate-700 border-dashed rounded-xl cursor-pointer bg-slate-900/50 hover:bg-slate-900 hover:border-indigo-500 transition-all group">
          <div className="flex flex-col items-center justify-center pt-5 pb-6">
            <Upload size={32} className="mb-3 text-slate-400 group-hover:text-indigo-400 transition-colors" />
            <p className="mb-2 text-sm text-slate-300">
              <span className="font-semibold text-indigo-400">{multiple ? t('admin.tasks.click_to_upload') : t('admin.tasks.click_to_upload')}</span>
              {' '}{t('admin.tasks.drag_and_drop')}
            </p>
            <p className="text-xs text-slate-500">{acceptedFormats}</p>
          </div>
          <input ref={inputRef} type="file" className="hidden" multiple={multiple} accept={accept} onChange={handleFiles} />
        </label>
      )}

      {isOverLimit && maxFiles && (
        <p className="text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 p-3 rounded-lg">
          {t('admin.tasks.max_files_reached', { count: maxFiles })}
        </p>
      )}

      {files.length > 0 && (
        <div className="flex flex-col gap-2 mt-1">
          <span className="text-xs text-slate-400 font-medium">
            {multiple ? t('admin.tasks.files_selected', { count: files.length }) : t('admin.tasks.file_selected')}
          </span>
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-2 bg-slate-900 border border-white/5 rounded-lg px-3 py-2 text-xs text-slate-300">
              <FileText size={16} className="text-indigo-400 flex-shrink-0" />
              <span className="truncate flex-1">{f.name}</span>
              <span className="text-slate-500">{(f.size / 1024).toFixed(1)} KB</span>
              <button type="button" onClick={() => removeFile(i)} className="text-slate-500 hover:text-rose-400 transition-colors ml-1">
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
      {required && (
        <input type="text" required value={totalCount > 0 ? 'ok' : ''} onChange={() => {}} onInvalid={(e) => { e.preventDefault(); setError(true); }} tabIndex={-1} style={{ position: 'absolute', opacity: 0, pointerEvents: 'none', width: 0, height: 0 }} aria-hidden="true" />
      )}
      {error && (
        <p className="text-[11px] text-rose-400 font-medium animate-fadein">
          {t('common.required_field_input')}
        </p>
      )}
    </div>
  );
}
