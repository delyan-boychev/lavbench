import React from 'react';

export default function ToggleField({ label, id, checked, onChange, disabled = false }) {
  const isChecked = !!checked;
  return (
    <div className="flex items-center gap-2 select-none">
      <label className="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          id={id}
          className="sr-only"
          checked={isChecked}
          onChange={onChange}
          disabled={disabled}
        />
        <div
          className={`relative w-9 h-5 rounded-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:rounded-full after:h-4 after:w-4 after:transition-all ${
            isChecked
              ? 'bg-indigo-600 after:translate-x-full after:bg-white'
              : 'bg-slate-800 after:bg-slate-500'
          } ${disabled ? 'opacity-55' : ''}`}
        />
        {label && <span className="ml-3 text-xs font-semibold text-slate-300">{label}</span>}
      </label>
    </div>
  );
}
