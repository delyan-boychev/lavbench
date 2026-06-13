import React from 'react';

export default function ToggleField({ label, id, checked, onChange, disabled }) {
  return (
    <div className="flex items-center gap-2 select-none">
      <label className="relative inline-flex items-center cursor-pointer">
        <input 
          type="checkbox" 
          id={id}
          className="sr-only peer" 
          checked={!!checked} 
          onChange={onChange}
          disabled={disabled}
        />
        <div className="relative w-9 h-5 bg-slate-800 rounded-full peer peer-checked:after:translate-x-full peer-checked:bg-indigo-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-500 peer-checked:after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-disabled:opacity-55"></div>
        {label && <span className="ml-3 text-xs font-semibold text-slate-300">{label}</span>}
      </label>
    </div>
  );
}
