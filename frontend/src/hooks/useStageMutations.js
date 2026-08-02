import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useCreateStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, ...body } = variables;
      return api.post(`/challenges/${challengeId}/stages`, body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useUpdateStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId, ...body } = variables;
      return api.put(`/challenges/${challengeId}/stages/${stageId}`, body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useDeleteStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId } = variables;
      return api.delete(`/challenges/${challengeId}/stages/${stageId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useFinalizeStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId } = variables;
      return api.post(`/challenges/${challengeId}/stages/${stageId}/finalize`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useToggleRevealStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, stageId } = variables;
      return api.put(`/challenges/${challengeId}/stages/${stageId}/reveal-results`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}
