import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

export function useCreateChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ body) => api.post('/challenges', body).then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useUpdateChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { id, ...body } = variables;
      return api.put(`/challenges/${id}`, body).then(requireOk);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useDeleteChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.delete(`/challenges/${id}`).then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useFinalizeChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { id, reveal_results } = variables;
      return api
        .post(`/challenges/${id}/finalize`, { reveal_results: Boolean(reveal_results) })
        .then(requireOk);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useToggleRevealChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { id, reveal_results } = variables;
      return api
        .put(`/challenges/${id}/reveal-results`, { reveal_results: Boolean(reveal_results) })
        .then(requireOk);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useArchiveToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.post(`/challenges/${id}/archive`).then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useExportChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.get(`/challenges/${id}/export`).then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useImportChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ formData) =>
      api.postForm('/challenges/import', formData).then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}
