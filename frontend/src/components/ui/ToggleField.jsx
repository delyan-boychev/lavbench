import React, { useId } from 'react';

/**
 * A switch with its label; `hint` is a one-line status under it, such as what the switch does now.
 * @param {{
 *   label?: React.ReactNode,
 *   id?: string,
 *   checked: boolean,
 *   onChange: (event: React.ChangeEvent<HTMLInputElement>) => void,
 *   disabled?: boolean,
 *   hint?: React.ReactNode,
 * }} props
 */
export default function ToggleField({ label, id, checked, onChange, disabled = false, hint = '' }) {
  const isChecked = !!checked;
  const fallbackId = useId();
  const hintId = `${id || fallbackId}-hint`;
  return (
    <div className="flex flex-col gap-1 select-none">
      <label className="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          id={id}
          className="sr-only"
          checked={isChecked}
          onChange={onChange}
          disabled={disabled}
          aria-describedby={hint ? hintId : undefined}
        />
        <div
          className={`relative w-9 h-5 shrink-0 rounded-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:rounded-full after:h-4 after:w-4 after:transition-all ${
            isChecked
              ? 'bg-indigo-600 after:translate-x-full after:bg-white'
              : 'bg-slate-800 after:bg-slate-500'
          } ${disabled ? 'opacity-55' : ''}`}
        />
        {label && <span className="ml-3 text-xs font-semibold text-slate-300">{label}</span>}
      </label>
      {hint && (
        <p id={hintId} className="ml-12 text-[10px] text-slate-400 leading-normal">
          {hint}
        </p>
      )}
    </div>
  );
}
