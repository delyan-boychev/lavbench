import api from './ApiService.js';

const TaskService = {
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/challenges/{challenge_id}/tasks']['post']['responses']['201']['content']['application/json'] }>} */
  create: (challengeId, fd) => api.postForm(`/challenges/${challengeId}/tasks`, fd),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/tasks/{task_id}']['put']['responses']['200']['content']['application/json'] }>} */
  update: (id, fd) => api.putForm(`/tasks/${id}`, fd),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/tasks/{task_id}']['delete']['responses']['200']['content']['application/json'] }>} */
  delete: (id) => api.delete(`/tasks/${id}`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/tasks/{task_id}/submit']['post']['responses']['202']['content']['application/json'] }>} */
  submit: (id, cells) => api.post(`/tasks/${id}/submit`, { selected_cells: cells }),
  getSubmissions: (id, page, perPage = 10) =>
    api.get(`/tasks/${id}/submissions${page ? `?page=${page}&per_page=${perPage}` : ''}`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/tasks/{task_id}/leaderboard']['get']['responses']['200']['content']['application/json'] }>} */
  getLeaderboard: (id) => api.get(`/tasks/${id}/leaderboard`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/submissions/{submission_id}']['get']['responses']['200']['content']['application/json'] }>} */
  getSubmissionDetail: (submissionId) => api.get(`/submissions/${submissionId}`),
  killSubmission: (submissionId) => api.post(`/submissions/${submissionId}/kill`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: any }>} */
  selectFinal: (submissionId) => api.post(`/submissions/${submissionId}/select-final`),
  getQueue: (page, perPage = 10) =>
    api.get(`/admin/submissions/queue?page=${page}&per_page=${perPage}`),
  clearQueue: () => api.post('/admin/submissions/queue/clear'),
  // Returns a direct URL string for anchor-based file downloads (streamed)
  getDownloadUrl: (taskId, filename) =>
    `/api/tasks/${taskId}/download/${encodeURIComponent(filename)}`,
};

export default TaskService;
