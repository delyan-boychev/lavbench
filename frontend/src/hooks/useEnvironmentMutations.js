import { useMutation, useQueryClient } from '@tanstack/react-query';
import EnvironmentService from '../services/EnvironmentService';
import { dataOf, environmentKeys } from './useEnvironmentQuery';

// Every admin action answers with the fresh environment, so the list updates without a refetch
function useEnvironmentAction(challengeId, action, { touchesChallenge = false } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) =>
      /** @type {Promise<any>} */ (dataOf(action(variables))),
    onSuccess: (environment) => {
      qc.setQueryData(environmentKeys.list(challengeId), (/** @type {any} */ list) =>
        Array.isArray(list?.environments)
          ? {
              ...list,
              environments: list.environments.map((row) =>
                row.id === environment.id ? environment : row,
              ),
            }
          : list,
      );
      if (touchesChallenge) {
        qc.invalidateQueries({ queryKey: ['admin-challenges'] });
        qc.invalidateQueries({ queryKey: ['challenges'] });
      }
    },
  });
}

export function usePublishEnvironment(challengeId) {
  return useEnvironmentAction(challengeId, (environmentId) =>
    EnvironmentService.publish(challengeId, environmentId),
  );
}

export function useExtendEnvironment(challengeId) {
  return useEnvironmentAction(
    challengeId,
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
