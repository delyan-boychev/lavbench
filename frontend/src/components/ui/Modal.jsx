import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

const SIZES = {
  sm: 'max-w-md',
  md: 'max-w-xl',
  lg: 'max-w-3xl',
  xl: 'max-w-5xl',
  '2xl': 'max-w-7xl',
};

export default function Modal({ isOpen, onClose, title, children, size = 'md', footer, bodyScrollable = true }) {
  const { t } = useTranslation();
  const [shouldRender, setShouldRender] = useState(isOpen);
  const [animateShow, setAnimateShow] = useState(false);

  // Handle opening and closing transition state
  useEffect(() => {
    if (isOpen) {
      setShouldRender(true);
      const timer = setTimeout(() => setAnimateShow(true), 10);
      return () => clearTimeout(timer);
    } else {
      setAnimateShow(false);
      const timer = setTimeout(() => setShouldRender(false), 200);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // Prevent body & html scroll when open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      document.documentElement.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
      document.documentElement.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
      document.documentElement.style.overflow = '';
    };
  }, [isOpen]);

  if (!shouldRender) return null;

  return createPortal(
    <div 
      className={`fixed inset-0 z-[150] bg-black/70 backdrop-blur-sm flex items-center justify-center p-6 md:p-10 overflow-hidden transition-opacity duration-200 ${
        animateShow ? 'opacity-100' : 'opacity-0'
      }`} 
      onClick={onClose}
    >
      <div 
        className={`bg-slate-900 border border-slate-800 rounded-xl shadow-2xl w-full max-h-[90vh] flex flex-col ${
          SIZES[size] || SIZES.md
        } transform transition-all duration-200 ${
          animateShow ? 'scale-100 opacity-100' : 'scale-95 opacity-0'
        }`}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4.5 border-b border-slate-800 flex-shrink-0">
          <h2 className="text-base font-semibold text-slate-100">{title}</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 cursor-pointer text-lg p-1.5 rounded-lg hover:bg-slate-800 leading-none transition-colors"
            title={t('common.close')}
          >✕</button>
        </div>

        {/* Body */}
        <div className={`p-6 flex-1 flex flex-col min-h-0 text-slate-300 ${
          bodyScrollable ? 'overflow-y-auto overscroll-contain scrollbar-thin' : 'overflow-hidden'
        }`}>
          {children}
        </div>

        {/* Optional footer */}
        {footer && (
          <div className="px-6 py-4 border-t border-slate-800 flex justify-end gap-2 flex-shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
