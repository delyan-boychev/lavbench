import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

const invalidateChallenges = (qc) => {
  qc.invalidateQueries({ queryKey: ['admin-challenges'] });
  qc.invalidateQueries({ queryKey: ['challenges'] });
};

export function useCreateStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, ...body } = variables;
      return api.post(`/challenges/${challengeId}/stages`, body).then(requireOk);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useUpdateStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId, ...body } = variables;
      return api.put(`/challenges/${challengeId}/stages/${stageId}`, body).then(requireOk);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useDeleteStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId } = variables;
      return api.delete(`/challenges/${challengeId}/stages/${stageId}`).then(requireOk);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useFinalizeStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId, reveal_results } = variables;
      return api
        .post(`/challenges/${challengeId}/stages/${stageId}/finalize`, {
          reveal_results: Boolean(reveal_results),
        })
        .then(requireOk);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useToggleRevealStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId, reveal_results } = variables;
      return api
        .put(`/challenges/${challengeId}/stages/${stageId}/reveal-results`, {
          reveal_results: Boolean(reveal_results),
        })
        .then(requireOk);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}
