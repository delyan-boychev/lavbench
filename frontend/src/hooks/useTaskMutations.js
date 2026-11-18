import { useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';
import TaskService from '../services/TaskService';

const invalidateChallenges = (qc) => {
  qc.invalidateQueries({ queryKey: ['admin-challenges'] });
  qc.invalidateQueries({ queryKey: ['challenges'] });
};

// Task files and Hugging Face data count toward each environment's disk and package
const invalidateTaskData = (qc) => {
  invalidateChallenges(qc);
  qc.invalidateQueries({ queryKey: ['environment'] });
};

/** Refresh what depends on a task's files, after an upload from the queue. */
export function useInvalidateTaskData() {
  const qc = useQueryClient();
  return useCallback(() => invalidateTaskData(qc), [qc]);
}

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

/** Remove a task's Hugging Face ZIP. */
export function useRemoveHfZip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (/** @type {{ taskId: string }} */ v) =>
      requireOk(await api.delete(TaskService.hfZipPath(v.taskId))),
    onSuccess: () => invalidateTaskData(qc),
  });
}

/** Remove one stored task file, with the admin's reason for a hidden file after publish. */
export function useDeleteTaskFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (/** @type {{ taskId: string, filename: string, reason?: string }} */ v) =>
      requireOk(await api.delete(TaskService.filePath(v.taskId, v.filename, { reason: v.reason }))),
    onSuccess: () => invalidateTaskData(qc),
  });
}
