import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';

const NotificationsContext = createContext(null);
// Toast state lives in its own context so showing a toast only re-renders the toast UI,
// not every component that merely needs the stable showToast/confirm actions
const ToastStateContext = createContext(null);

function ConfirmModal({ config }) {
  const [val, setVal] = useState('');
  const promptRef = useRef(null);
  const confirmRef = useRef(null);
  const cancelRef = useRef(null);

  React.useEffect(() => {
    if (config.isOpen) setVal('');
  }, [config.isOpen]);

  const footer = (
    <>
      {config.cancelText && (
        <Button ref={cancelRef} variant="secondary" onClick={config.onCancel}>
          {config.cancelText}
        </Button>
      )}
      <Button ref={confirmRef} onClick={() => config.onConfirm(val)}>
        {config.confirmText}
      </Button>
    </>
  );
  // Irreversible actions start on Cancel, so a stray Enter does not confirm them
  const initialFocusRef = config.isPrompt
    ? promptRef
    : config.focusCancel && config.cancelText
      ? cancelRef
      : confirmRef;

  return (
    <Modal
      isOpen={config.isOpen}
      onClose={config.onCancel}
      title={config.title}
      size="sm"
      footer={footer}
      initialFocusRef={initialFocusRef}
    >
      <div className="flex flex-col gap-4">
        {typeof config.message === 'string' ? (
          <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
            {config.message}
          </p>
        ) : (
          <div className="text-sm text-slate-300 leading-relaxed">{config.message}</div>
        )}
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
  const pendingCancelRef = useRef(/** @type {(() => void) | null} */ (null));
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
    focusCancel: false,
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
      focusCancel = false,
    }) => {
      // A newer dialog replaces the open one; settle the old caller as cancelled
      // so its await never hangs
      pendingCancelRef.current?.();
      return new Promise((resolve) => {
        const cancelValue = isPrompt ? null : false;
        let settled = false;
        const settle = (value) => {
          if (settled) return;
          settled = true;
          if (pendingCancelRef.current === cancel) pendingCancelRef.current = null;
          resolve(value);
        };
        const cancel = () => settle(cancelValue);
        pendingCancelRef.current = cancel;
        setConfirmConfig({
          isOpen: true,
          title,
          message,
          confirmText,
          cancelText,
          isPrompt,
          placeholder,
          focusCancel,
          onConfirm: (val) => {
            setConfirmConfig((prev) => ({ ...prev, isOpen: false }));
            settle(isPrompt ? val : true);
          },
          onCancel: () => {
            setConfirmConfig((prev) => ({ ...prev, isOpen: false }));
            cancel();
          },
        });
      });
    },
    [t],
  );

  const actions = useMemo(() => ({ showToast, confirm }), [showToast, confirm]);

  return (
    <NotificationsContext.Provider value={actions}>
      <ToastStateContext.Provider value={toast}>
        {children}
        <ConfirmModal config={confirmConfig} />
      </ToastStateContext.Provider>
    </NotificationsContext.Provider>
  );
};

export const useNotifications = () => {
  const ctx = useContext(NotificationsContext);
  if (!ctx) throw new Error('useNotifications must be used within NotificationsProvider');
  return ctx;
};

export const useToast = () => {
  const ctx = useContext(ToastStateContext);
  if (!ctx) throw new Error('useToast must be used within NotificationsProvider');
  return ctx;
};
