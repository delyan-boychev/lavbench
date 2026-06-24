import api from './ApiService.js';

const ChallengeService = {
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges']['get']['responses']['200']['content']['application/json'] }>} */
  getAll: () => api.get('/challenges'),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}']['get']['responses']['200']['content']['application/json'] }>} */
  getOne: (id) => api.get(`/challenges/${id}`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges']['post']['responses']['200']['content']['application/json'] }>} */
  create: (data) => api.post('/challenges', data),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}']['put']['responses']['200']['content']['application/json'] }>} */
  update: (id, data) => api.put(`/challenges/${id}`, data),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}']['delete']['responses']['200']['content']['application/json'] }>} */
  delete: (id) => api.delete(`/challenges/${id}`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}/finalize']['post']['responses']['200']['content']['application/json'] }>} */
  finalize: (id, data) => api.post(`/challenges/${id}/finalize`, data),
  finalizeStage: (challengeId, stageId, data) =>
    api.post(`/challenges/${challengeId}/stages/${stageId}/finalize`, data),
  toggleReveal: (id, reveal_results) =>
    api.put(`/challenges/${id}/reveal-results`, { reveal_results }),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}/archive']['post']['responses']['200']['content']['application/json'] }>} */
  archiveToggle: (id) => api.post(`/challenges/${id}/archive`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}/leaderboard']['get']['responses']['200']['content']['application/json'] }>} */
  getLeaderboard: (id) => api.get(`/challenges/${id}/leaderboard`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}/manual-points']['post']['responses']['200']['content']['application/json'] }>} */
  saveManualPoints: (id, data) => api.post(`/challenges/${id}/manual-points`, data),
  parseNotebook: (id, file) => {
    const fd = new FormData();
    fd.append('file', file);
    /** @type {Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}/parse-notebook']['post']['responses']['200']['content']['application/json'] }>} */
    return api.postForm(`/challenges/${id}/parse-notebook`, fd);
  },
  downloadSubmission: (challengeId, taskId, userId) =>
    api.getBlob(`/challenges/${challengeId}/tasks/${taskId}/users/${userId}/download`),
  downloadAuditLogs: (challengeId) => api.getBlob(`/challenges/${challengeId}/audit-logs/download`),
  downloadSubmissionUrl: (challengeId, taskId, userId) =>
    `/challenges/${challengeId}/tasks/${taskId}/users/${userId}/download`,
  downloadAuditLogsUrl: (challengeId) => `/challenges/${challengeId}/audit-logs/download`,
};

export default ChallengeService;
