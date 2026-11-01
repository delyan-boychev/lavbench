import api from './ApiService.js';

export const LAB_WINDOW_NAME = 'lavbench-lab';

const stagePath = (challengeId, stageId) => `/challenges/${challengeId}/stages/${stageId}`;

const EnvironmentService = {
  getWorkspaceImages: (challengeId) => api.get(`/challenges/${challengeId}/compute/images`),
  getStageCompute: (challengeId, stageId) => api.get(`${stagePath(challengeId, stageId)}/compute`),
  putStageCompute: (challengeId, stageId, body) =>
    api.put(`${stagePath(challengeId, stageId)}/compute`, body),
  syncStageCompute: (challengeId, stageId) =>
    api.post(`${stagePath(challengeId, stageId)}/compute/sync`),
  putTaskWorkspacePaths: (taskId, body) => api.put(`/tasks/${taskId}/workspace-paths`, body),
  getEnvironment: (challengeId, stageId) =>
    api.get(`${stagePath(challengeId, stageId)}/environment`),
  launchEnvironment: (challengeId, stageId) =>
    api.post(`${stagePath(challengeId, stageId)}/environment`),
  submitFromWorkspace: (taskId) => api.post(`/tasks/${taskId}/submit-from-workspace`),
};

/**
 * @returns {Window | null}
 */
export function openLabWindow() {
  return window.open('about:blank', LAB_WINDOW_NAME);
}

/**
 * @param {{ launch_url: string, launch_token: string }} launch
 * @param {Window | null} labWindow
 */
export function postLaunchForm(launch, labWindow) {
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = launch.launch_url;
  form.target = labWindow && !labWindow.closed ? LAB_WINDOW_NAME : '_self';
  form.style.display = 'none';
  const token = document.createElement('input');
  token.type = 'hidden';
  token.name = 'launch_token';
  token.value = launch.launch_token;
  form.appendChild(token);
  document.body.appendChild(form);
  form.submit();
  form.remove();
}

export default EnvironmentService;
