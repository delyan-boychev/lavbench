import React, { useRef, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export default function FileUploader({
  files = [],
  onChange,
  accept,
  multiple = false,
  label,
  description,
  required = false,
  requiredFiles = [],
  maxFiles,
  className = '',
}) {
  const { t } = useTranslation();
  const inputRef = useRef(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (files.length > 0) setError(false);
  }, [files]);

  const handleFiles = (e) => {
    const incoming = Array.from(e.target.files);
    if (multiple) {
      onChange(prev => {
        const existingNames = new Set(prev.map(f => f.name));
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

  const missingRequired = requiredFiles.filter(
    name => !files.some(f => f.name === name)
  );

  const isOverLimit = maxFiles && files.length >= maxFiles;

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

      {!isOverLimit && (
        <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-slate-700 border-dashed rounded-xl cursor-pointer bg-slate-900/50 hover:bg-slate-900 hover:border-indigo-500 transition-all group">
          <div className="flex flex-col items-center justify-center pt-5 pb-6">
            <svg className="w-8 h-8 mb-3 text-slate-400 group-hover:text-indigo-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
            <p className="mb-2 text-sm text-slate-300">
              <span className="font-semibold text-indigo-400">{multiple ? t('admin.tasks.click_to_upload') : t('admin.tasks.click_to_upload')}</span>
              {' '}{t('admin.tasks.drag_and_drop')}
            </p>
            <p className="text-xs text-slate-500">{acceptedFormats}</p>
          </div>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            multiple={multiple}
            accept={accept}
            onChange={handleFiles}
          />
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
            {multiple
              ? t('admin.tasks.files_selected', { count: files.length })
              : t('admin.tasks.file_selected')}
          </span>
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-2 bg-slate-900 border border-white/5 rounded-lg px-3 py-2 text-xs text-slate-300">
              <svg className="w-4 h-4 text-indigo-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
              <span className="truncate flex-1">{f.name}</span>
              <span className="text-slate-500">{(f.size / 1024).toFixed(1)} KB</span>
              <button
                type="button"
                onClick={() => removeFile(i)}
                className="text-slate-500 hover:text-rose-400 transition-colors ml-1"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
          ))}
        </div>
      )}
      {required && (
        <input
          type="text"
          required
          value={files.length > 0 ? 'ok' : ''}
          onChange={() => {}}
          onInvalid={(e) => { e.preventDefault(); setError(true); }}
          tabIndex={-1}
          style={{ position: 'absolute', opacity: 0, pointerEvents: 'none', width: 0, height: 0 }}
          aria-hidden="true"
        />
      )}
      {error && (
        <p className="text-[11px] text-rose-400 font-medium animate-fadein">
          {t('common.required_field_input')}
        </p>
      )}
    </div>
  );
}
