import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/ApiService';

// Users, competitors and competitor search all read /admin/users
const invalidateUserLists = (qc) => {
  qc.invalidateQueries({ queryKey: ['admin-users'] });
  qc.invalidateQueries({ queryKey: ['admin-competitors'] });
  qc.invalidateQueries({ queryKey: ['competitor-search'] });
};

export function useRegisterUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ body) => api.post('/admin/register-user', body),
    onSuccess: () => invalidateUserLists(qc),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ variables) => {
      const { id, ...body } = variables;
      return api.put(`/admin/users/${id}`, body);
    },
    onSuccess: () => invalidateUserLists(qc),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ userId) => api.delete(`/admin/users/${userId}`),
    onSuccess: () => invalidateUserLists(qc),
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
