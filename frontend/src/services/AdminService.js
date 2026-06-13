import api from './ApiService.js';

const AdminService = {
  getUsers:           ()       => api.get('/admin/users'),
  deleteUser:         (id)     => api.delete(`/admin/users/${id}`),
  registerCompetitor: (data)   => api.post('/admin/register-competitor', data),
  registerUser:       (data)   => api.post('/admin/register-user', data),
  importCSV:          (fd)     => api.postForm('/admin/import-competitors-csv', fd),
  // Backup returns raw response (blob streaming)
  downloadBackup: async () => {
    const token = localStorage.getItem('token');
    return fetch('/api/admin/backup', {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    });
  },
};

export default AdminService;
