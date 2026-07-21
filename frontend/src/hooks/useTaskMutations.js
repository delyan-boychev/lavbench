import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { challengeId, formData } = variables;
      return api.postForm(`/challenges/${challengeId}/tasks`, formData);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useUpdateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { taskId, formData } = variables;
      return api.putForm(`/tasks/${taskId}`, formData);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ taskId) => api.delete(`/tasks/${taskId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-challenges'] }),
  });
}
