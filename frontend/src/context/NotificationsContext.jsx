import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import Modal from '../components/ui/Modal';

const NotificationsContext = createContext(null);

function ConfirmModal({ config }) {
  const [val, setVal] = useState('');
  const promptRef = useRef(null);
  const confirmRef = useRef(null);

  React.useEffect(() => {
    if (config.isOpen) setVal('');
  }, [config.isOpen]);

  const footer = (
    <>
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
        ref={confirmRef}
        type="button"
        onClick={() => config.onConfirm(val)}
        className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg shadow-md hover:shadow-indigo-500/10 transition-all cursor-pointer"
      >
        {config.confirmText}
      </button>
    </>
  );

  return (
    <Modal
      isOpen={config.isOpen}
      onClose={config.onCancel}
      title={config.title}
      size="sm"
      footer={footer}
      initialFocusRef={config.isPrompt ? promptRef : confirmRef}
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
          {config.message}
        </p>
        {config.isPrompt && (
          <input
            ref={promptRef}
            type="text"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder={config.placeholder}
            className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 rounded-lg text-sm text-slate-100 font-sans focus:outline-none"
            onKeyDown={(e) => {
              if (e.key === 'Enter') config.onConfirm(val);
            }}
          />
        )}
      </div>
    </Modal>
  );
}

export const NotificationsProvider = ({ children }) => {
  const { t } = useTranslation();
  const toastTimeoutRef = useRef(null);
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
    if (toastTimeoutRef.current !== null) {
      clearTimeout(toastTimeoutRef.current);
    }
    setToast({ show: true, message, type });
    toastTimeoutRef.current = setTimeout(() => {
      setToast({ show: false, message: '', type: 'success' });
      toastTimeoutRef.current = null;
    }, 4000);
  }, []);

  useEffect(
    () => () => {
      if (toastTimeoutRef.current !== null) {
        clearTimeout(toastTimeoutRef.current);
      }
    },
    [],
  );

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
