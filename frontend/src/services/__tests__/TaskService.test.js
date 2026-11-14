import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../ApiService.js', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    getBlob: vi.fn(),
  },
}));

import TaskService from '../TaskService';
import api from '../ApiService.js';

describe('TaskService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('submit', () => {
    it('submits selected notebook cells', async () => {
      const cells = ['cell1', 'cell2'];
      api.post.mockResolvedValue({ ok: true, status: 200, data: { submitted: true } });

      const result = await TaskService.submit(1, cells);

      expect(api.post).toHaveBeenCalledWith('/tasks/1/submit', { selected_cells: cells });
      expect(result.data).toEqual({ submitted: true });
    });
  });

  describe('getSubmissions', () => {
    it('gets submissions without pagination', async () => {
      const submissions = [{ id: 1, status: 'pending' }];
      api.get.mockResolvedValue({ ok: true, status: 200, data: submissions });

      const result = await TaskService.getSubmissions(1);

      expect(api.get).toHaveBeenCalledWith('/tasks/1/submissions');
      expect(result.data).toEqual(submissions);
    });

    it('gets submissions with pagination', async () => {
      const submissions = [{ id: 2, status: 'graded' }];
      api.get.mockResolvedValue({ ok: true, status: 200, data: submissions });

      const result = await TaskService.getSubmissions(1, 2, 20);

      expect(api.get).toHaveBeenCalledWith('/tasks/1/submissions?page=2&per_page=20');
      expect(result.data).toEqual(submissions);
    });

    it('uses default perPage when only page is provided', async () => {
      api.get.mockResolvedValue({ ok: true, status: 200, data: [] });

      await TaskService.getSubmissions(1, 1);

      expect(api.get).toHaveBeenCalledWith('/tasks/1/submissions?page=1&per_page=10');
    });
  });

  describe('getSubmissionDetail', () => {
    it('returns submission detail by submission id', async () => {
      const detail = { id: 10, status: 'graded', score: 85 };
      api.get.mockResolvedValue({ ok: true, status: 200, data: detail });

      const result = await TaskService.getSubmissionDetail(10);

      expect(api.get).toHaveBeenCalledWith('/submissions/10');
      expect(result.data).toEqual(detail);
    });
  });

  describe('downloadFile', () => {
    it('fetches the task file as a blob response', async () => {
      const response = { ok: true, status: 200 };
      api.getBlob.mockResolvedValue(response);

      const result = await TaskService.downloadFile(1, 'train.csv');

      expect(api.getBlob).toHaveBeenCalledWith('/tasks/1/download/train.csv');
      expect(result).toBe(response);
    });

    it('encodes special characters in filename', async () => {
      api.getBlob.mockResolvedValue({ ok: true, status: 200 });

      await TaskService.downloadFile(1, 'my file.ipynb');

      expect(api.getBlob).toHaveBeenCalledWith('/tasks/1/download/my%20file.ipynb');
    });
  });

  describe('killSubmission', () => {
    it('kills a submission by id', async () => {
      api.post.mockResolvedValue({ ok: true, status: 200, data: { message: 'Killed' } });

      const result = await TaskService.killSubmission('sub-1');

      expect(api.post).toHaveBeenCalledWith('/submissions/sub-1/kill');
      expect(result.data).toEqual({ message: 'Killed' });
    });

    it('handles kill error', async () => {
      api.post.mockResolvedValue({
        ok: false,
        status: 400,
        data: { code: 'ERR_SUBMISSION_NOT_KILLABLE', error: 'Cannot kill' },
      });

      const result = await TaskService.killSubmission('sub-1');

      expect(result.ok).toBe(false);
      expect(result.data.code).toBe('ERR_SUBMISSION_NOT_KILLABLE');
    });
  });

  describe('getQueue', () => {
    it('fetches queue with pagination', async () => {
      const queueData = { items: [{ id: 'q1' }], total: 1, page: 1, pages: 1 };
      api.get.mockResolvedValue({ ok: true, status: 200, data: queueData });

      const result = await TaskService.getQueue(1, 20);

      expect(api.get).toHaveBeenCalledWith('/admin/submissions/queue?page=1&per_page=20');
      expect(result.data).toEqual(queueData);
    });

    it('uses default perPage of 10', async () => {
      api.get.mockResolvedValue({
        ok: true,
        status: 200,
        data: { items: [], total: 0, page: 1, pages: 1 },
      });

      await TaskService.getQueue(2);

      expect(api.get).toHaveBeenCalledWith('/admin/submissions/queue?page=2&per_page=10');
    });

    it('handles queue fetch error', async () => {
      api.get.mockResolvedValue({
        ok: false,
        status: 403,
        data: { code: 'ERR_FORBIDDEN', error: 'Access denied' },
      });

      const result = await TaskService.getQueue(1);

      expect(result.ok).toBe(false);
      expect(result.data.code).toBe('ERR_FORBIDDEN');
    });
  });

  describe('clearQueue', () => {
    it('clears the queue', async () => {
      api.post.mockResolvedValue({
        ok: true,
        status: 200,
        data: { message: 'Cleared 2 submission(s)' },
      });

      const result = await TaskService.clearQueue();

      expect(api.post).toHaveBeenCalledWith('/admin/submissions/queue/clear');
      expect(result.data.message).toContain('Cleared');
    });

    it('handles clear queue error', async () => {
      api.post.mockResolvedValue({
        ok: false,
        status: 403,
        data: { code: 'ERR_FORBIDDEN', error: 'Admins only' },
      });

      const result = await TaskService.clearQueue();

      expect(result.ok).toBe(false);
      expect(result.data.code).toBe('ERR_FORBIDDEN');
    });
  });
});
