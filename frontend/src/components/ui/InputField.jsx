import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export default function InputField({
  label,
  type = 'text',
  value,
  onChange,
  placeholder = '',
  required = false,
  disabled = false,
  className = '',
  hint = '',
  id = '',
  multiline = false,
  rows = 4,
  min = undefined,
  max = undefined,
}) {
  const { t } = useTranslation();
  const [error, setError] = useState(false);
  const inputRef = useRef(null);
  const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

  useEffect(() => {
    if (value) setError(false); // eslint-disable-line react-hooks/set-state-in-effect
  }, [value]);

  const handleInvalid = (e) => {
    e.preventDefault();
    setError(true);
  };

  const sharedClassName = `surface-input ${
    error ? '!border-rose-500/60 !ring-1 !ring-rose-500/30' : ''
  }`;

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && (
        <label htmlFor={inputId} className="text-xs font-semibold text-slate-300">
          {label}
          {required && <span className="text-rose-500 ml-1">*</span>}
        </label>
      )}
      {multiline ? (
        <textarea
          ref={inputRef}
          id={inputId}
          rows={rows}
          className={`${sharedClassName} resize-y font-sans`}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          required={required}
          disabled={disabled}
          onInvalid={required ? handleInvalid : undefined}
        />
      ) : (
        <input
          ref={inputRef}
          id={inputId}
          type={type}
          className={sharedClassName}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          required={required}
          disabled={disabled}
          min={min}
          max={max}
          onInvalid={required ? handleInvalid : undefined}
        />
      )}
      {error && (
        <p className="text-[11px] text-rose-400 font-medium animate-fadein">
          {t('common.required_field_input')}
        </p>
      )}
      {!error && hint && <p className="text-[10px] text-slate-400 mt-1 leading-normal">{hint}</p>}
    </div>
  );
}
