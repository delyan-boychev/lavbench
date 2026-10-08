import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

// Users, competitors and competitor search all read /admin/users
const invalidateUserLists = (qc) => {
  qc.invalidateQueries({ queryKey: ['admin-users'] });
  qc.invalidateQueries({ queryKey: ['admin-competitors'] });
  qc.invalidateQueries({ queryKey: ['competitor-search'] });
};

export function useRegisterCompetitor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ body) => api.post('/admin/register-competitor', body),
    onSuccess: () => invalidateUserLists(qc),
  });
}

export function useCsvImportCompetitors() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ formData) =>
      api.postForm('/admin/import-competitors-csv', formData),
    onSuccess: () => invalidateUserLists(qc),
  });
}
