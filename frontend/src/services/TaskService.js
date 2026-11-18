import api from './ApiService.js';

const TaskService = {
  /** @type {(...args: any[]) => Promise<{ ok: boolean, data: import('../types/api').paths['/api/tasks/{task_id}/submit']['post']['responses']['202']['content']['application/json'] }>} */
  submit: (id, cells) => api.post(`/tasks/${id}/submit`, { selected_cells: cells }),
  /** Submit submission.parquet and solution.ipynb from the task folder of the workspace. */
  submitWorkspace: (id) => api.post(`/tasks/${id}/submit-workspace`),
  /** The emergency path: the same two files, uploaded by hand while the admin allows it. */
  submitFile: (id, submission, notebook) => {
    const form = new FormData();
    form.append('submission', submission);
    form.append('notebook', notebook);
    return api.postForm(`/tasks/${id}/submit-file`, form);
  },
  /** The cells of solution.ipynb from the student's workspace, for the cell picker. */
  loadWorkspaceNotebook: (id) => api.post(`/tasks/${id}/workspace-notebook`),
  /** The Parquet or the notebook of a file-task submission (admin and jury). */
  downloadSubmissionFile: (submissionId, kind) =>
    api.getBlob(`/submissions/${submissionId}/files/${kind}`),
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
