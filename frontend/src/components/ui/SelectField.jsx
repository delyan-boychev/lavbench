import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

export default function SelectField({
  label = null,
  value,
  onChange,
  options = [],
  className = '',
  required = false,
  disabled = false,
  placeholder = '',
  multiple = false,
  searchable = false,
  error = false,
}) {
  const { t } = useTranslation();
  const resolvedPlaceholder = placeholder || t('common.select_option', 'Select option');
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [hasError, setHasError] = useState(false);

  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const dropdownRef = useRef(null);
  const searchInputRef = useRef(null);

  const [coords, setCoords] = useState({ top: 0, left: 0, width: 0, openUp: false });

  const updateCoords = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      const openUp = spaceBelow < 260 && spaceAbove > spaceBelow;
      setCoords({
        top: openUp ? rect.top - 4 : rect.bottom + 4,
        left: rect.left,
        width: rect.width,
        openUp,
      });
    }
  };

  useEffect(() => {
    if (value && (!multiple || value.length > 0)) {
      setHasError(false);
    }
  }, [value, multiple]);

  useEffect(() => {
    function handleClickOutside(event) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target) &&
        !(dropdownRef.current && dropdownRef.current.contains(event.target))
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const handleScroll = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      updateCoords();
      window.addEventListener('scroll', handleScroll, { capture: true, passive: true });
      window.addEventListener('resize', updateCoords);
    }
    return () => {
      window.removeEventListener('scroll', handleScroll, { capture: true });
      window.removeEventListener('resize', updateCoords);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      setSearchQuery('');
    } else {
      setTimeout(() => {
        if (searchInputRef.current) {
          searchInputRef.current.focus();
        }
      }, 50);
    }
  }, [isOpen]);

  const handleInvalid = (e) => {
    e.preventDefault();
    setHasError(true);
  };

  const toggleOption = (optValue) => {
    if (multiple) {
      const currentValues = Array.isArray(value) ? value : [];
      let newValues;
      if (currentValues.includes(optValue)) {
        newValues = currentValues.filter((v) => v !== optValue);
      } else {
        newValues = [...currentValues, optValue];
      }
      onChange(newValues);
    } else {
      onChange(optValue);
      setIsOpen(false);
    }
  };

  const isSelected = (optValue) => {
    if (multiple) {
      return Array.isArray(value) && value.includes(optValue);
    }
    return value === optValue;
  };

  // Determine button label text
  let buttonLabel = resolvedPlaceholder;
  if (multiple) {
    const selectedArr = Array.isArray(value) ? value : [];
    const selectedOpts = options.filter((o) => selectedArr.includes(o.value));
    if (selectedOpts.length > 0) {
      buttonLabel = selectedOpts.map((o) => o.label).join(', ');
    }
  } else {
    const selectedOpt = options.find((o) => o.value === value);
    if (selectedOpt) {
      buttonLabel = selectedOpt.label;
    }
  }

  const showSearch = searchable || options.length > 5;
  const filteredOptions = options.filter(
    (opt) =>
      (opt.label || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (String(opt.value) || '').toLowerCase().includes(searchQuery.toLowerCase()),
  );

  return (
    <div ref={containerRef} className={`flex flex-col gap-1.5 relative w-full ${className}`}>
      {label && (
        <span className="text-xs font-semibold text-slate-300">
          {label}
          {required && <span className="text-rose-500 ml-1">*</span>}
        </span>
      )}

      <div className="relative w-full">
        <button
          ref={triggerRef}
          type="button"
          disabled={disabled}
          onClick={() => setIsOpen(!isOpen)}
          className={`flex items-center justify-between w-full px-3 py-2 text-sm text-slate-200 bg-slate-900 border rounded-lg hover:border-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
            error || hasError ? 'border-rose-500/60 ring-1 ring-rose-500/30' : 'border-slate-800'
          }`}
        >
          <span className="truncate mr-2 text-left">{buttonLabel}</span>
          <svg
            className={`text-slate-500 transition-transform duration-200 w-4 h-4 flex-shrink-0 ${
              isOpen ? 'rotate-180 text-indigo-400' : ''
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2.5"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {isOpen &&
          !disabled &&
          createPortal(
            <div
              ref={dropdownRef}
              style={{
                position: 'fixed',
                top: `${coords.top}px`,
                left: `${coords.left}px`,
                width: `${coords.width}px`,
                transform: coords.openUp ? 'translateY(-100%)' : 'none',
              }}
              className="bg-slate-950/95 border border-slate-800/80 rounded-lg shadow-2xl backdrop-blur-md max-h-60 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-700 z-[9999] flex flex-col"
            >
              {showSearch && (
                <div className="sticky top-0 bg-slate-950/95 border-b border-slate-800/80 p-2 z-20 backdrop-blur-md">
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('common.search_placeholder', 'Search...')}
                    className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 rounded text-xs text-slate-100 placeholder-slate-500 focus:outline-none"
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>
              )}
              <div className="py-1 overflow-y-auto flex-1">
                {options.length === 0 ? (
                  <div className="px-3 py-2 text-slate-500 italic text-sm">
                    {resolvedPlaceholder}
                  </div>
                ) : filteredOptions.length === 0 ? (
                  <div className="px-3 py-4 text-slate-500 italic text-center text-sm">
                    {t('common.no_results', 'No results found')}
                  </div>
                ) : (
                  filteredOptions.map((opt) => {
                    const selected = isSelected(opt.value);
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => toggleOption(opt.value)}
                        className={`flex items-center justify-between w-full px-3 py-2 text-left transition-colors duration-150 cursor-pointer ${
                          selected
                            ? 'bg-indigo-600/20 text-indigo-300 font-bold border-l-2 border-indigo-500'
                            : 'text-slate-300 hover:bg-slate-900 hover:text-white'
                        } text-sm`}
                      >
                        <span className="truncate mr-2">{opt.label}</span>
                        {selected && (
                          <svg
                            className="text-indigo-400 flex-shrink-0 w-4 h-4"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth="2.5"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </button>
                    );
                  })
                )}
              </div>
            </div>,
            document.body,
          )}
      </div>

      <select
        required={required}
        multiple={multiple}
        value={multiple ? (Array.isArray(value) ? value : []) : value || ''}
        onChange={(e) => {
          if (onChange) {
            if (multiple) {
              const selectedValues = Array.from(e.target.selectedOptions).map((o) => o.value);
              onChange(selectedValues);
            } else {
              onChange(e.target.value);
            }
          }
        }}
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
      >
        {!multiple && <option value="">{placeholder || ''}</option>}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {(error || hasError) && (
        <p className="text-[11px] text-rose-400 font-medium animate-fadein">
          {typeof error === 'string' ? error : t('common.required_field', 'This field is required')}
        </p>
      )}
    </div>
  );
}
