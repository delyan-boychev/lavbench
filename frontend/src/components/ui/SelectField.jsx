import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import CustomSelect from './CustomSelect';

export default function SelectField({
  label,
  value,
  onChange,
  options = [],
  className = '',
  required = false,
  disabled = false,
  placeholder = '',
}) {
  const { t } = useTranslation();
  const [error, setError] = useState(false);
  const selectRef = useRef(null);

  useEffect(() => {
    if (value) setError(false);
  }, [value]);

  const handleInvalid = (e) => {
    e.preventDefault();
    setError(true);
  };

  return (
    <div className={`flex flex-col gap-1.5 ${className}`} style={{ position: 'relative' }}>
      {label && (
        <span className="text-xs font-semibold text-slate-300">
          {label}
          {required && <span className="text-rose-500 ml-1">*</span>}
        </span>
      )}
      <CustomSelect
        options={options}
        value={value}
        onChange={onChange}
        disabled={disabled}
        placeholder={placeholder}
        error={error}
      />
      {required && (
        <select
          ref={selectRef}
          required
          value={value}
          onChange={() => {}}
          onInvalid={handleInvalid}
          tabIndex={-1}
          style={{
            position: 'absolute',
            opacity: 0,
            pointerEvents: 'none',
            width: '100%',
            height: '100%',
            top: 0,
            left: 0,
            zIndex: -1,
          }}
          aria-hidden="true"
        >
          <option value="">{placeholder || ''}</option>
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      )}
      {error && (
        <p className="text-[11px] text-rose-400 font-medium animate-fadein">
          {t('common.required_field')}
        </p>
      )}
    </div>
  );
}
