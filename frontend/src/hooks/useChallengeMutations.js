import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

const invalidateChallenges = (qc) => {
  qc.invalidateQueries({ queryKey: ['admin-challenges'] });
  qc.invalidateQueries({ queryKey: ['challenges'] });
};

export function useCreateChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ body) => api.post('/challenges', body).then(requireOk),
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useUpdateChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { id, ...body } = variables;
      return api.put(`/challenges/${id}`, body).then(requireOk);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useDeleteChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.delete(`/challenges/${id}`).then(requireOk),
    onSuccess: () => invalidateChallenges(qc),
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
    onSuccess: () => invalidateChallenges(qc),
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
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useArchiveToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ id) => api.post(`/challenges/${id}/archive`).then(requireOk),
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useExportChallenge() {
  return useMutation({
    mutationFn: async (/** @type {any} */ id) => {
      const res = await api.getBlob(`/challenges/${id}/export`);
      const data = res.ok ? null : await res.json().catch(() => null);
      return requireOk({ ok: res.ok, status: res.status, data, res });
    },
  });
}

export function useImportChallenge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ formData) =>
      api.postForm('/challenges/import', formData).then(requireOk),
    onSuccess: () => invalidateChallenges(qc),
  });
}
