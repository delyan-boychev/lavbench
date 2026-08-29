import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

export function useForceBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/admin/backups/force').then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups'] }),
  });
}

export function useDeleteBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (filename) => api.delete(`/admin/backups/${filename}`).then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups'] }),
  });
}
