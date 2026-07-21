import React, { createContext, useContext, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

const NotificationsContext = createContext(null);

function ConfirmModal({ config }) {
  const [val, setVal] = useState('');

  React.useEffect(() => {
    if (config.isOpen) setVal('');
  }, [config.isOpen]);

  if (!config.isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-[200] bg-black/70 backdrop-blur-sm flex items-center justify-center p-6 animate-fadein">
      <div
        className="bg-slate-900 border border-slate-800 rounded-xl shadow-2xl w-full max-w-md overflow-hidden transform scale-100 transition-all duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-slate-800">
          <h2 className="text-base font-semibold text-slate-100">{config.title}</h2>
        </div>
        <div className="p-6 flex flex-col gap-4">
          <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
            {config.message}
          </p>
          {config.isPrompt && (
            <input
              type="text"
              value={val}
              onChange={(e) => setVal(e.target.value)}
              placeholder={config.placeholder}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 rounded-lg text-sm text-slate-100 font-sans focus:outline-none"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') config.onConfirm(val);
              }}
            />
          )}
        </div>
        <div className="px-6 py-4 border-t border-slate-800 flex justify-end gap-2 bg-slate-950/20">
          {config.cancelText && (
            <button
              type="button"
              onClick={config.onCancel}
              className="px-4 py-2 text-xs font-semibold text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700/80 rounded-lg transition-colors cursor-pointer"
            >
              {config.cancelText}
            </button>
          )}
          <button
            type="button"
            onClick={() => config.onConfirm(val)}
            className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg shadow-md hover:shadow-indigo-500/10 transition-all cursor-pointer"
          >
            {config.confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export const NotificationsProvider = ({ children }) => {
  const { t } = useTranslation();
  const [toast, setToast] = useState({ show: false, message: '', type: 'success' });
  const [confirmConfig, setConfirmConfig] = useState({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: null,
    onCancel: null,
    confirmText: '',
    cancelText: '',
    isPrompt: false,
    placeholder: '',
  });

  const showToast = useCallback((message, type = 'success') => {
    setToast({ show: true, message, type });
    setTimeout(() => setToast({ show: false, message: '', type: 'success' }), 4000);
  }, []);

  const confirm = useCallback(
    ({
      title,
      message,
      confirmText = t('common.confirm'),
      cancelText = t('common.cancel'),
      isPrompt = false,
      placeholder = '',
    }) => {
      return new Promise((resolve) => {
        setConfirmConfig({
          isOpen: true,
          title,
          message,
          confirmText,
          cancelText,
          isPrompt,
          placeholder,
          onConfirm: (val) => {
            setConfirmConfig((prev) => ({ ...prev, isOpen: false }));
            resolve(isPrompt ? val : true);
          },
          onCancel: () => {
            setConfirmConfig((prev) => ({ ...prev, isOpen: false }));
            resolve(isPrompt ? null : false);
          },
        });
      });
    },
    [t],
  );

  return (
    <NotificationsContext.Provider value={{ toast, showToast, confirm }}>
      {children}
      <ConfirmModal config={confirmConfig} />
    </NotificationsContext.Provider>
  );
};

export const useNotifications = () => {
  const ctx = useContext(NotificationsContext);
  if (!ctx) throw new Error('useNotifications must be used within NotificationsProvider');
  return ctx;
};
