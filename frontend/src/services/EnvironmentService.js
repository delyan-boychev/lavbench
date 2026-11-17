import api from './ApiService.js';

const environmentPath = (challengeId, environmentId) =>
  `/challenges/${challengeId}/environments/${environmentId}`;

const EnvironmentService = {
  /** @type {(challengeId: string) => Promise<{ ok: boolean, status: number, data: any }>} */
  list: (challengeId) => api.get(`/challenges/${challengeId}/environments`),
  getCatalog: () => api.get('/environment/images'),
  publish: (challengeId, environmentId) =>
    api.post(`${environmentPath(challengeId, environmentId)}/publish`),
  extend: (challengeId, environmentId, body) =>
    api.post(`${environmentPath(challengeId, environmentId)}/extension`, body),
  getWorkspaces: (challengeId, environmentId) =>
    api.get(`${environmentPath(challengeId, environmentId)}/workspaces`),
  liveUrl: (challengeId) => `/api/challenges/${challengeId}/environment/live`,
  getForTask: (taskId) => api.get(`/tasks/${taskId}/environment`),
  launch: (taskId) => api.post(`/tasks/${taskId}/environment/launch`),
};

export default EnvironmentService;
