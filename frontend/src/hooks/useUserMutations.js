import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useRegisterUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ body) => api.post('/admin/register-user', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { id, ...body } = variables;
      return api.put(`/admin/users/${id}`, body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ userId) => api.delete(`/admin/users/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (/** @type {any} */ userId) => api.post(`/admin/users/${userId}/reset-password`),
  });
}

export function useBulkResetPasswords() {
  return useMutation({
    mutationFn: (/** @type {any} */ challengeId) =>
      api.post(`/admin/challenges/${challengeId}/reset-all-passwords`),
  });
}
