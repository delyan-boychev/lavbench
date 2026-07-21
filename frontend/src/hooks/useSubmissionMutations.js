import { useMutation, useQueryClient } from '@tanstack/react-query';
import TaskService from '../services/TaskService';

export function useSelectFinal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ submissionId) =>
      fetch(`/api/submissions/${submissionId}/select-final`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }).then((r) => {
        if (!r.ok) return r.json().then((d) => Promise.reject(d));
        return r.json();
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['submissions'] }),
  });
}

export function useKillSubmission() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ submissionId) =>
      TaskService.killSubmission(submissionId).then((r) => {
        if (!r.ok) return r.json().then((d) => Promise.reject(d));
        return r.data;
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions'] });
      qc.invalidateQueries({ queryKey: ['admin-submissions'] });
    },
  });
}

export function useClearQueue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      TaskService.clearQueue().then((r) => {
        if (!r.ok) return r.json().then((d) => Promise.reject(d));
        return r;
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['queue'] }),
  });
}
