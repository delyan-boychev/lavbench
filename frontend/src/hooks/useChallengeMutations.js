import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useCreateChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ body) => api.post('/challenges', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useUpdateChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { id, ...body } = variables;
      return api.put(`/challenges/${id}`, body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useDeleteChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.delete(`/challenges/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useFinalizeChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.post(`/challenges/${id}/finalize`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useToggleRevealChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.put(`/challenges/${id}/reveal-results`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useArchiveToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.post(`/challenges/${id}/archive`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useExportChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.get(`/challenges/${id}/export`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useImportChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ formData) => api.postForm('/challenges/import', formData),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}
