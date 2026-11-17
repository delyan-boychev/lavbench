import api from './ApiService.js';

const ownerPath = (challengeId, stageId) =>
  stageId
    ? `/challenges/${challengeId}/stages/${stageId}/environment`
    : `/challenges/${challengeId}/environment`;

const environmentPath = (challengeId, environmentId) =>
  `/challenges/${challengeId}/environments/${environmentId}`;

const EnvironmentService = {
  /** @type {(challengeId: string, stageId?: string | null) => Promise<{ ok: boolean, status: number, data: any }>} */
  get: (challengeId, stageId) => api.get(ownerPath(challengeId, stageId)),
  /** @type {(challengeId: string, stageId: string | null, body: object) => Promise<{ ok: boolean, status: number, data: any }>} */
  save: (challengeId, stageId, body) => api.put(ownerPath(challengeId, stageId), body),
  getImages: (challengeId) => api.get(`/challenges/${challengeId}/environment/images`),
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
