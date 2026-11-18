import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

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

/** The admin's emergency upload switch for a file task, applied at once. */
export function useSetEmergencyUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (/** @type {{ taskId: string, enabled: boolean, reason: string }} */ v) =>
      requireOk(
        await api.put(`/tasks/${v.taskId}/emergency-upload`, {
          enabled: v.enabled,
          reason: v.reason,
        }),
      ),
    onSuccess: () => invalidateChallenges(qc),
  });
}
