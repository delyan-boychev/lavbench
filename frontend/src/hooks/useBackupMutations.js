import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useForceBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/admin/backups/force'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups'] }),
  });
}

export function useDeleteBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (filename) => api.delete(`/admin/backups/${filename}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups'] }),
  });
}
