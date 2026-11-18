import { useQuery } from '@tanstack/react-query';
import EnvironmentService from '../services/EnvironmentService';
import { requireOk, retryUnlessClientError } from '../services/apiResult';
import { LIVE_QUERY_OPTIONS } from './useSSEInvalidation';

export const environmentKeys = {
  challenge: (challengeId) => ['environment', String(challengeId)],
  list: (challengeId) => ['environment', String(challengeId), 'list'],
  workspaces: (challengeId, environmentId) => [
    'environment',
    String(challengeId),
    'workspaces',
    String(environmentId),
  ],
  catalog: ['workspace-catalog'],
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

/**
 * False only when the catalog says nanoColab is switched off on this platform.
 * @param {{ data?: { available?: boolean } }} catalog
 */
export function workspacesOffered(catalog) {
  return catalog.data?.available !== false;
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
 * Each stage's environment, or the competition's when it has no stages.
 * @param {string} challengeId
 * @param {LiveOptions} [options]
 */
export function useEnvironmentsQuery(challengeId, options = {}) {
  const { enabled = true, ...rest } = options;
  return useQuery({
    queryKey: environmentKeys.list(challengeId),
    queryFn: () =>
      dataOf(EnvironmentService.list(challengeId)).then((data) => data.environments || []),
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
 * nanoColab's images and profiles and the work space limits; `available: false` means
 * workspaces are off on this platform.
 * @param {boolean} enabled
 */
export function useWorkspaceCatalogQuery(enabled) {
  return useQuery({
    queryKey: environmentKeys.catalog,
    queryFn: () => dataOf(EnvironmentService.getCatalog()),
    enabled,
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

/**
 * Whether the environment that ships this task's files is published (its public files and
 * folder are then fixed). The stage's environment, or the competition's when it has none.
 * @param {{ id: string, workspaces_enabled?: boolean } | null | undefined} challenge
 * @param {string | null | undefined} stageId undefined for a task not yet created
 */
export function useTaskPublished(challenge, stageId) {
  const { data } = useEnvironmentsQuery(challenge?.id, {
    enabled: Boolean(challenge?.workspaces_enabled) && stageId !== undefined,
  });
  const env = (data || []).find((e) => String(e.stage_id ?? '') === String(stageId ?? ''));
  return Boolean(env?.published_at);
}
