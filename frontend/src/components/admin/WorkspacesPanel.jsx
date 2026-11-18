import React, { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Settings } from 'lucide-react';
import Button from '../ui/Button';
import QueryErrorState from '../ui/QueryErrorState';
import Skeleton from '../ui/Skeleton';
import EnvironmentCard from './EnvironmentCard';
import {
  useEnvironmentLiveInterval,
  useEnvironmentLiveSubscription,
} from '../../context/EnvironmentLiveContext';
import { useEnvironmentsQuery } from '../../hooks/useEnvironmentQuery';
import { useEditorFocus } from '../../hooks/useEditorFocus';

/**
 * The Workspaces view of a competition: status and actions per stage, no settings.
 * @param {{
 *   challenge: any,
 *   readOnly: boolean,
 *   onClose: () => void,
 *   onEditSettings?: () => void,
 * }} props
 */
export default function WorkspacesPanel({ challenge, readOnly, onClose, onEditSettings }) {
  const { t } = useTranslation();
  const rootRef = useRef(null);
  // Opens from its top like an editor and returns to the competition's button on Back
  useEditorFocus(rootRef, { focus: 'heading' });
  const refetchInterval = useEnvironmentLiveInterval(challenge.id);
  useEnvironmentLiveSubscription(challenge.id, true);
  const query = useEnvironmentsQuery(challenge.id, { refetchInterval });

  return (
    <div
      ref={rootRef}
      className="admin-card p-5 md:p-8 animate-fadein"
      data-testid="workspaces-panel"
    >
      <div className="flex flex-wrap justify-between items-start gap-3 mb-4">
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-white">
            {t('environment.view.title', { title: challenge.title })}
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {!readOnly && onEditSettings && (
            <Button variant="secondary" onClick={onEditSettings}>
              <Settings size={14} aria-hidden="true" />
              {t('environment.view.edit_settings')}
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            <ArrowLeft size={14} aria-hidden="true" />
            {t('environment.view.back')}
          </Button>
        </div>
      </div>
      {query.isError && !query.data ? (
        <QueryErrorState onRetry={query.refetch} minHeight={120} />
      ) : !query.data ? (
        <Skeleton count={4} width="100%" height="1rem" />
      ) : (
        <div className="flex flex-col gap-5">
          {query.data.map((env) => (
            <EnvironmentCard
              key={env.stage_id || 'competition'}
              env={env}
              challenge={challenge}
              readOnly={readOnly}
              refetchInterval={refetchInterval}
            />
          ))}
        </div>
      )}
    </div>
  );
}
