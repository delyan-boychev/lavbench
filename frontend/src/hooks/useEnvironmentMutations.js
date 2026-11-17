import { useMutation, useQueryClient } from '@tanstack/react-query';
import EnvironmentService from '../services/EnvironmentService';
import { dataOf, environmentKeys } from './useEnvironmentQuery';

// Every admin action answers with the fresh environment, so the panel updates without a refetch
function useEnvironmentAction(challengeId, stageId, action, { touchesChallenge = false } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) =>
      /** @type {Promise<any>} */ (dataOf(action(variables))),
    onSuccess: (environment) => {
      qc.setQueryData(environmentKeys.owner(challengeId, stageId), environment);
      if (touchesChallenge) {
        qc.invalidateQueries({ queryKey: ['admin-challenges'] });
        qc.invalidateQueries({ queryKey: ['challenges'] });
      }
    },
  });
}

export function useSaveEnvironment(challengeId, stageId) {
  return useEnvironmentAction(challengeId, stageId, (body) =>
    EnvironmentService.save(challengeId, stageId, body),
  );
}

export function usePublishEnvironment(challengeId, stageId) {
  return useEnvironmentAction(challengeId, stageId, (environmentId) =>
    EnvironmentService.publish(challengeId, environmentId),
  );
}

export function useExtendEnvironment(challengeId, stageId) {
  return useEnvironmentAction(
    challengeId,
    stageId,
    ({ environmentId, ...body }) => EnvironmentService.extend(challengeId, environmentId, body),
    { touchesChallenge: true },
  );
}

export function useLaunchWorkspace() {
  return useMutation({
    mutationFn: (/** @type {string} */ taskId) =>
      /** @type {Promise<{ launch_url: string, launch_token: string, expires_at: string, open_path: string }>} */ (
        dataOf(EnvironmentService.launch(taskId))
      ),
  });
}
