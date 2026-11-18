import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import FormView from '../ui/FormView';
import CompetitionFields from './CompetitionFields';
import WorkspaceSettingsSection from './WorkspaceSettingsSection';
import { useWorkspaceCatalogQuery, workspacesOffered } from '../../hooks/useEnvironmentQuery';
import { useFieldErrors } from '../../hooks/useFieldErrors';
import { workspaceDraft, workspacePayload } from '../../utils/workspaceSetting';

export default function ChallengeConfig({
  handleCreateChallenge,
  newChallenge,
  setNewChallenge,
  isCreatingChallenge,
}) {
  const { t } = useTranslation();
  const catalog = useWorkspaceCatalogQuery(true);
  const [workspace, setWorkspace] = useState(() => workspaceDraft(null));
  const workspaceErrors = useFieldErrors('workspace.');

  const submit = async (e) => {
    workspaceErrors.reset();
    const payload = workspacesOffered(catalog) ? workspacePayload(workspace) : undefined;
    const error = await handleCreateChallenge(e, payload);
    if (error) workspaceErrors.capture(error);
  };

  return (
    <FormView
      title={t('admin.create_new_challenge')}
      onSubmit={submit}
      showBack={false}
      errors={workspaceErrors.errors}
      submitLabel={t('admin.create_competition_btn')}
      submitting={isCreatingChallenge}
    >
      <CompetitionFields
        value={newChallenge}
        onChange={(patch) => setNewChallenge({ ...newChallenge, ...patch })}
        idPrefix="create"
      />
      <WorkspaceSettingsSection
        draft={workspace}
        onChange={setWorkspace}
        catalog={catalog}
        timezone={newChallenge.timezone || 'UTC'}
        errors={workspaceErrors.errors}
        onFieldEdit={workspaceErrors.clear}
      />
    </FormView>
  );
}
