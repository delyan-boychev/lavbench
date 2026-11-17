import { useQuery } from '@tanstack/react-query';
import EnvironmentService from '../services/EnvironmentService';
import { requireOk, retryUnlessClientError } from '../services/apiResult';
import { LIVE_QUERY_OPTIONS } from './useSSEInvalidation';

export const environmentKeys = {
  challenge: (challengeId) => ['environment', String(challengeId)],
  owner: (challengeId, stageId) => [
    'environment',
    String(challengeId),
    'owner',
    stageId ? String(stageId) : null,
  ],
  workspaces: (challengeId, environmentId) => [
    'environment',
    String(challengeId),
    'workspaces',
    String(environmentId),
  ],
  images: (challengeId) => ['workspace-images', String(challengeId)],
  task: (challengeId, taskId) => ['environment', String(challengeId), 'task', String(taskId)],
};

/**
 * Off (404), not enabled (409) or not visible (403): the UI then shows nothing.
 * @param {unknown} error
 */
export function isEnvironmentHidden(error) {
  const status = /** @type {{ status?: number } | null} */ (error)?.status;
  return status === 403 || status === 404 || status === 409;
}

export const dataOf = (promise) => promise.then(requireOk).then((res) => res.data);

/**
 * @typedef {{
 *   refetchInterval?: number | false,
 *   refetchOnMount?: boolean | 'always',
 *   enabled?: boolean,
 * }} LiveOptions
 */

/**
 * @param {string} challengeId
 * @param {string | null | undefined} stageId
 * @param {LiveOptions} [options]
 */
export function useEnvironmentQuery(challengeId, stageId, options = {}) {
  const { enabled = true, ...rest } = options;
  return useQuery({
    queryKey: environmentKeys.owner(challengeId, stageId),
    queryFn: () => dataOf(EnvironmentService.get(challengeId, stageId)),
    enabled: enabled && !!challengeId,
    retry: retryUnlessClientError,
    ...LIVE_QUERY_OPTIONS,
    ...rest,
  });
}

/**
 * @param {string} challengeId
 * @param {string | null | undefined} environmentId
 * @param {LiveOptions} [options]
 */
export function useWorkspacesQuery(challengeId, environmentId, options = {}) {
  const { enabled = true, ...rest } = options;
  return useQuery({
    queryKey: environmentKeys.workspaces(challengeId, environmentId),
    queryFn: () =>
      dataOf(EnvironmentService.getWorkspaces(challengeId, environmentId)).then(
        (data) => data.workspaces || [],
      ),
    enabled: enabled && !!challengeId && !!environmentId,
    retry: retryUnlessClientError,
    ...LIVE_QUERY_OPTIONS,
    ...rest,
  });
}

/**
 * @param {string} challengeId
 * @param {boolean} enabled
 */
export function useWorkspaceImagesQuery(challengeId, enabled) {
  return useQuery({
    queryKey: environmentKeys.images(challengeId),
    queryFn: () =>
      dataOf(EnvironmentService.getImages(challengeId)).then((data) => data.images || []),
    enabled: enabled && !!challengeId,
    retry: retryUnlessClientError,
    staleTime: 5 * 60_000,
  });
}

/**
 * @param {string} challengeId
 * @param {string} taskId
 * @param {LiveOptions} [options]
 */
export function useTaskEnvironmentQuery(challengeId, taskId, options = {}) {
  const { enabled = true, ...rest } = options;
  return useQuery({
    queryKey: environmentKeys.task(challengeId, taskId),
    queryFn: () => dataOf(EnvironmentService.getForTask(taskId)),
    enabled: enabled && !!taskId,
    retry: retryUnlessClientError,
    ...LIVE_QUERY_OPTIONS,
    ...rest,
  });
}
