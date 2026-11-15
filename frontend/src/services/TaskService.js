import api from './ApiService.js';

const TaskService = {
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/tasks/{task_id}/submit']['post']['responses']['202']['content']['application/json'] }>} */
  submit: (id, cells) => api.post(`/tasks/${id}/submit`, { selected_cells: cells }),
  getSubmissions: (id, page, perPage = 10) =>
    api.get(`/tasks/${id}/submissions${page ? `?page=${page}&per_page=${perPage}` : ''}`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/submissions/{submission_id}']['get']['responses']['200']['content']['application/json'] }>} */
  getSubmissionDetail: (submissionId) => api.get(`/submissions/${submissionId}`),
  killSubmission: (submissionId) => api.post(`/submissions/${submissionId}/kill`),
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: any }>} */
  selectFinal: (submissionId) => api.post(`/submissions/${submissionId}/select-final`),
  getQueue: (page, perPage = 10) =>
    api.get(`/admin/submissions/queue?page=${page}&per_page=${perPage}`),
  clearQueue: () => api.post('/admin/submissions/queue/clear'),
  downloadFile: (taskId, filename) =>
    api.getBlob(`/tasks/${taskId}/download/${encodeURIComponent(filename)}`),
  getDownloadUrl: (taskId, filename) =>
    `/api/tasks/${taskId}/download/${encodeURIComponent(filename)}`,
};

export default TaskService;
