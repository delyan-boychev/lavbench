import React from 'react';
import { useTranslation } from 'react-i18next';
import Button from './Button';
import EmptyState from './EmptyState';

export default function QueryErrorState({ message = '', onRetry = null, minHeight = 160 }) {
  const { t } = useTranslation();

  return (
    <div role="alert">
      <EmptyState
        message={message || t('common.unexpected_error')}
        minHeight={minHeight}
        surface={false}
      >
        {onRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            {t('common.retry')}
          </Button>
        )}
      </EmptyState>
    </div>
  );
}
