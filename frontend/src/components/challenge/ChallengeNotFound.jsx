import React from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { SearchX } from 'lucide-react';
import EmptyState from '../ui/EmptyState';

export default function ChallengeNotFound() {
  const { t } = useTranslation();
  return (
    <div className="animate-fadein" data-testid="challenge-not-found">
      <EmptyState minHeight={300} message={t('challenge.not_found')} icon={<SearchX size={32} />}>
        <Link to="/challenges" className="btn btn-secondary btn-sm mt-2">
          {t('challenge.back_to_challenges')}
        </Link>
      </EmptyState>
    </div>
  );
}
