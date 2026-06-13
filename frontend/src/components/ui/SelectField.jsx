import React from 'react';
import CustomSelect from './CustomSelect';

export default function SelectField({
  label,
  value,
  onChange,
  options = [],
  className = '',
  required = false,
  disabled = false,
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && (
        <span className="text-xs font-semibold text-slate-300">
          {label}{required && <span className="text-rose-500 ml-1">*</span>}
        </span>
      )}
      <CustomSelect
        options={options}
        value={value}
        onChange={onChange}
        disabled={disabled}
        placeholder={label ? `Select ${label.toLowerCase()}` : "Select option"}
      />
    </div>
  );
}
