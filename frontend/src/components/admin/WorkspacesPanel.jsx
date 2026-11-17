import React from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft } from 'lucide-react';
import Button from '../ui/Button';
import Notice from '../ui/Notice';
import QueryErrorState from '../ui/QueryErrorState';
import Skeleton from '../ui/Skeleton';
import EnvironmentCard from './EnvironmentCard';
import {
  useEnvironmentLiveInterval,
  useEnvironmentLiveSubscription,
} from '../../context/EnvironmentLiveContext';
import { useEnvironmentsQuery, useWorkspaceCatalogQuery } from '../../hooks/useEnvironmentQuery';

/**
 * The Workspaces view of a competition: status and actions per stage, no settings.
 * @param {{ challenge: any, readOnly: boolean, onClose: () => void }} props
 */
export default function WorkspacesPanel({ challenge, readOnly, onClose }) {
  const { t } = useTranslation();
  const refetchInterval = useEnvironmentLiveInterval(challenge.id);
  useEnvironmentLiveSubscription(challenge.id, true);
  const query = useEnvironmentsQuery(challenge.id, { refetchInterval });
  // Image names come from the catalog, which only admins may read
  const catalog = useWorkspaceCatalogQuery(!readOnly);
  const imageName = (id) => catalog.data?.images?.find((image) => image.image_id === id)?.name;

  return (
    <div className="admin-card p-5 md:p-8 animate-fadein" data-testid="workspaces-panel">
      <div className="flex flex-wrap justify-between items-start gap-3 mb-4">
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-white">
            {t('environment.view.title', { title: challenge.title })}
          </h2>
        </div>
        <Button variant="secondary" onClick={onClose}>
          <ArrowLeft size={14} aria-hidden="true" />
          {t('environment.view.back')}
        </Button>
      </div>
      {!readOnly && <Notice className="mb-5">{t('environment.view.intro')}</Notice>}
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
              imageName={imageName(env.image_id)}
              readOnly={readOnly}
              refetchInterval={refetchInterval}
            />
          ))}
        </div>
      )}
    </div>
  );
}
