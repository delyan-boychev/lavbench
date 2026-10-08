import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

const invalidateChallenges = (qc) => {
  qc.invalidateQueries({ queryKey: ['admin-challenges'] });
  qc.invalidateQueries({ queryKey: ['challenges'] });
};

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, formData } = variables;
      return api.postForm(`/challenges/${challengeId}/tasks`, formData);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useUpdateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { taskId, formData } = variables;
      return api.putForm(`/tasks/${taskId}`, formData);
    },
    onSuccess: () => invalidateChallenges(qc),
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ taskId) => api.delete(`/tasks/${taskId}`),
    onSuccess: () => invalidateChallenges(qc),
  });
}
