import api from './ApiService.js';

const ChallengeService = {
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
};

export default ChallengeService;
