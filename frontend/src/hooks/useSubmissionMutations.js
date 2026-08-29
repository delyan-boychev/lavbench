import { useMutation, useQueryClient } from '@tanstack/react-query';
import TaskService from '../services/TaskService';
import { requireOk } from '../services/apiResult';

export function useSelectFinal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ submissionId) =>
      TaskService.selectFinal(submissionId)
        .then(requireOk)
        .then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['submissions'] }),
  });
}

export function useKillSubmission() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ submissionId) =>
      TaskService.killSubmission(submissionId)
        .then(requireOk)
        .then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions'] });
      qc.invalidateQueries({ queryKey: ['admin-submissions'] });
    },
  });
}

export function useClearQueue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => TaskService.clearQueue().then(requireOk),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['queue'] }),
  });
}
