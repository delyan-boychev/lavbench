import React from 'react';

export default function SelectField({
  label,
  value,
  onChange,
  options = [],
  className = '',
  required = false,
  disabled = false,
  id = ''
}) {
  const selectId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && (
        <label htmlFor={selectId} className="text-xs font-semibold text-slate-300">
          {label}{required && <span className="text-rose-500 ml-1">*</span>}
        </label>
      )}
      <select
        id={selectId}
        className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        value={value}
        onChange={onChange}
        required={required}
        disabled={disabled}
      >
        {options.map(opt => (
          <option key={opt.value} value={opt.value} className="bg-slate-950">
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
