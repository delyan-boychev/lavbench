import React from 'react';
import { useTranslation } from 'react-i18next';

export default function LoadingIndicator({ message = '', className = '' }) {
  const { t } = useTranslation();
  const resolvedMessage = message || t('common.loading');

  return (
    <div role="status" className={`flex items-center justify-center gap-2 ${className}`}>
      <span
        aria-hidden="true"
        className="animate-spin w-5 h-5 border-2 border-slate-700 border-t-indigo-500 rounded-full"
      />
      <span className="text-sm text-slate-400">{resolvedMessage}</span>
    </div>
  );
}
