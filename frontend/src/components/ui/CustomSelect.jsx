import React, { useState, useEffect, useRef } from 'react';

export default function CustomSelect({ 
  options = [], 
  value, 
  onChange, 
  placeholder = "Select option", 
  disabled = false,
  size = 'md'
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectedOption = options.find(opt => opt.value === value);
  const isSm = size === 'sm';

  return (
    <div ref={containerRef} className="relative inline-block text-left z-[100] w-full min-w-[160px]">
      <div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setIsOpen(!isOpen)}
          className={`flex items-center justify-between w-full px-3 text-slate-200 bg-slate-900 border border-slate-800 rounded-lg hover:border-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
            isSm ? 'py-1.5 text-xs font-semibold' : 'py-2 text-sm'
          }`}
        >
          <span className="truncate mr-2">
            {selectedOption ? selectedOption.label : placeholder}
          </span>
          <svg
            className={`text-slate-500 transition-transform duration-200 ${isOpen ? 'rotate-180 text-indigo-400' : ''} ${
              isSm ? 'w-3.5 h-3.5' : 'w-4 h-4'
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2.5"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {isOpen && !disabled && (
        <div className="absolute left-0 mt-1.5 w-full bg-slate-950/95 border border-slate-800/80 rounded-lg shadow-2xl backdrop-blur-md max-h-60 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-850 z-[110]">
          <div className="py-1">
            {options.length === 0 ? (
              <div className={`px-3 py-2 text-slate-500 italic ${isSm ? 'text-xs' : 'text-sm'}`}>
                {placeholder}
              </div>
            ) : (
              options.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    onChange(opt.value);
                    setIsOpen(false);
                  }}
                  className={`flex items-center justify-between w-full px-3 py-2 text-left transition-colors duration-150 cursor-pointer ${
                    opt.value === value
                      ? 'bg-indigo-650/20 text-indigo-300 font-bold border-l-2 border-indigo-500'
                      : 'text-slate-300 hover:bg-slate-900 hover:text-white'
                  } ${isSm ? 'text-xs' : 'text-sm'}`}
                >
                  <span className="truncate mr-2">{opt.label}</span>
                  {opt.value === value && (
                    <svg className={`text-indigo-400 flex-shrink-0 ${isSm ? 'w-3.5 h-3.5' : 'w-4 h-4'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
