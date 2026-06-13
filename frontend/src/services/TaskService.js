import api from './ApiService.js';

const TaskService = {
  create:         (challengeId, fd)    => api.postForm(`/challenges/${challengeId}/tasks`, fd),
  update:         (id, fd)             => api.putForm(`/tasks/${id}`, fd),
  delete:         (id)                 => api.delete(`/tasks/${id}`),
  submit:         (id, cells)          => api.post(`/tasks/${id}/submit`, { selected_cells: cells }),
  getSubmissions: (id, page, perPage = 10) => api.get(`/tasks/${id}/submissions${page ? `?page=${page}&per_page=${perPage}` : ''}`),
  getLeaderboard: (id)                 => api.get(`/tasks/${id}/leaderboard`),
  // Returns a direct URL string for anchor-based file downloads (streamed)
  getDownloadUrl: (taskId, filename)   => `/api/tasks/${taskId}/download/${encodeURIComponent(filename)}`,
};

export default TaskService;
