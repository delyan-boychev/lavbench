import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../ApiService.js', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    postForm: vi.fn(),
    putForm: vi.fn(),
  },
}));

import TaskService from '../TaskService';
import api from '../ApiService.js';

describe('TaskService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('create', () => {
    it('creates a task with FormData', async () => {
      const fd = new FormData();
      fd.append('title', 'Test Task');
      const created = { id: 1, title: 'Test Task' };
      api.postForm.mockResolvedValue({ ok: true, status: 201, data: created });

      const result = await TaskService.create(1, fd);

      expect(api.postForm).toHaveBeenCalledWith('/challenges/1/tasks', fd);
      expect(result.data).toEqual(created);
    });

    it('handles creation error', async () => {
      const fd = new FormData();
      api.postForm.mockResolvedValue({ ok: false, status: 422, data: { error: 'Invalid' } });

      const result = await TaskService.create(1, fd);

      expect(result.ok).toBe(false);
      expect(result.status).toBe(422);
    });
  });

  describe('update', () => {
    it('updates a task with FormData', async () => {
      const fd = new FormData();
      fd.append('title', 'Updated');
      api.putForm.mockResolvedValue({ ok: true, status: 200, data: { id: 1, title: 'Updated' } });

      const result = await TaskService.update(1, fd);

      expect(api.putForm).toHaveBeenCalledWith('/tasks/1', fd);
      expect(result.data.title).toBe('Updated');
    });
  });

  describe('delete', () => {
    it('deletes a task', async () => {
      api.delete.mockResolvedValue({ ok: true, status: 204, data: null });

      const result = await TaskService.delete(1);

      expect(api.delete).toHaveBeenCalledWith('/tasks/1');
      expect(result.ok).toBe(true);
    });
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

  describe('getLeaderboard', () => {
    it('returns task leaderboard', async () => {
      const lb = [{ rank: 1, name: 'Alice', score: 95 }];
      api.get.mockResolvedValue({ ok: true, status: 200, data: lb });

      const result = await TaskService.getLeaderboard(1);

      expect(api.get).toHaveBeenCalledWith('/tasks/1/leaderboard');
      expect(result.data).toEqual(lb);
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

  describe('getDownloadUrl', () => {
    it('returns a download URL string for the given filename', () => {
      const url = TaskService.getDownloadUrl(1, 'solution.ipynb');
      expect(url).toBe('/api/tasks/1/download/solution.ipynb');
    });

    it('encodes special characters in filename', () => {
      const url = TaskService.getDownloadUrl(1, 'my file.ipynb');
      expect(url).toBe('/api/tasks/1/download/my%20file.ipynb');
    });
  });
});
