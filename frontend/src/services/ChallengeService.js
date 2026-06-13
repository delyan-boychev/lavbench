import api from './ApiService.js';

const ChallengeService = {
  getAll:        ()          => api.get('/challenges'),
  getOne:        (id)        => api.get(`/challenges/${id}`),
  create:        (data)      => api.post('/challenges', data),
  update:        (id, data)  => api.put(`/challenges/${id}`, data),
  delete:        (id)        => api.delete(`/challenges/${id}`),
  finalize:      (id)        => api.post(`/challenges/${id}/finalize`),
  archiveToggle: (id)        => api.post(`/challenges/${id}/archive`),
  parseNotebook: (id, file)  => {
    const fd = new FormData();
    fd.append('file', file);
    return api.postForm(`/challenges/${id}/parse-notebook`, fd);
  },
};

export default ChallengeService;
