import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useRegisterCompetitor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ body) => api.post('/admin/register-competitor', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-competitors'] }),
  });
}

export function useCsvImportCompetitors() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ formData) =>
      api.postForm('/admin/import-competitors-csv', formData),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-competitors'] }),
  });
}
