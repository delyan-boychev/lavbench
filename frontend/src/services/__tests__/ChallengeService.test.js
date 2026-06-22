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

import ChallengeService from '../ChallengeService';
import api from '../ApiService.js';

describe('ChallengeService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getAll', () => {
    it('returns list of challenges', async () => {
      const challenges = [{ id: 1, title: 'Test Challenge' }];
      api.get.mockResolvedValue({ ok: true, status: 200, data: challenges });

      const result = await ChallengeService.getAll();

      expect(api.get).toHaveBeenCalledWith('/challenges');
      expect(result).toEqual({ ok: true, status: 200, data: challenges });
    });

    it('handles errors', async () => {
      api.get.mockResolvedValue({ ok: false, status: 500, data: { error: 'Server error' } });

      const result = await ChallengeService.getAll();

      expect(api.get).toHaveBeenCalledWith('/challenges');
      expect(result.ok).toBe(false);
      expect(result.status).toBe(500);
    });
  });

  describe('getOne', () => {
    it('returns a single challenge by id', async () => {
      const challenge = { id: 1, title: 'Test' };
      api.get.mockResolvedValue({ ok: true, status: 200, data: challenge });

      const result = await ChallengeService.getOne(1);

      expect(api.get).toHaveBeenCalledWith('/challenges/1');
      expect(result.data).toEqual(challenge);
    });

    it('handles 404 when challenge not found', async () => {
      api.get.mockResolvedValue({ ok: false, status: 404, data: { error: 'Not found' } });

      const result = await ChallengeService.getOne(999);

      expect(result.ok).toBe(false);
      expect(result.status).toBe(404);
    });
  });

  describe('create', () => {
    it('creates a new challenge', async () => {
      const newChallenge = { id: 2, title: 'New Challenge' };
      api.post.mockResolvedValue({ ok: true, status: 201, data: newChallenge });

      const result = await ChallengeService.create({ title: 'New Challenge' });

      expect(api.post).toHaveBeenCalledWith('/challenges', { title: 'New Challenge' });
      expect(result.data).toEqual(newChallenge);
    });

    it('handles validation error (400)', async () => {
      api.post.mockResolvedValue({ ok: false, status: 400, data: { error: 'Validation failed' } });

      const result = await ChallengeService.create({ invalid: true });

      expect(result.ok).toBe(false);
      expect(result.status).toBe(400);
    });
  });

  describe('update', () => {
    it('updates an existing challenge', async () => {
      const updated = { id: 1, title: 'Updated' };
      api.put.mockResolvedValue({ ok: true, status: 200, data: updated });

      const result = await ChallengeService.update(1, { title: 'Updated' });

      expect(api.put).toHaveBeenCalledWith('/challenges/1', { title: 'Updated' });
      expect(result.data).toEqual(updated);
    });
  });

  describe('delete', () => {
    it('deletes a challenge', async () => {
      api.delete.mockResolvedValue({ ok: true, status: 204, data: null });

      const result = await ChallengeService.delete(1);

      expect(api.delete).toHaveBeenCalledWith('/challenges/1');
      expect(result.ok).toBe(true);
    });
  });

  describe('finalize', () => {
    it('finalizes challenge scores', async () => {
      const payload = { scores: [10, 20] };
      api.post.mockResolvedValue({ ok: true, status: 200, data: { finalized: true } });

      const result = await ChallengeService.finalize(1, payload);

      expect(api.post).toHaveBeenCalledWith('/challenges/1/finalize', payload);
      expect(result.data).toEqual({ finalized: true });
    });
  });

  describe('archiveToggle', () => {
    it('toggles archive status', async () => {
      api.post.mockResolvedValue({ ok: true, status: 200, data: { archived: true } });

      const result = await ChallengeService.archiveToggle(1);

      expect(api.post).toHaveBeenCalledWith('/challenges/1/archive');
      expect(result.data.archived).toBe(true);
    });
  });

  describe('getLeaderboard', () => {
    it('returns challenge leaderboard', async () => {
      const leaderboard = [{ rank: 1, name: 'Alice', score: 100 }];
      api.get.mockResolvedValue({ ok: true, status: 200, data: leaderboard });

      const result = await ChallengeService.getLeaderboard(1);

      expect(api.get).toHaveBeenCalledWith('/challenges/1/leaderboard');
      expect(result.data).toEqual(leaderboard);
    });
  });

  describe('saveManualPoints', () => {
    it('saves manual points for a participant', async () => {
      const data = { participant_id: 1, points: 50 };
      api.post.mockResolvedValue({ ok: true, status: 200, data: { saved: true } });

      const result = await ChallengeService.saveManualPoints(1, data);

      expect(api.post).toHaveBeenCalledWith('/challenges/1/manual-points', data);
      expect(result.ok).toBe(true);
    });
  });

  describe('parseNotebook', () => {
    it('parses notebook file via form data', async () => {
      const file = new File(['content'], 'notebook.ipynb', { type: 'application/json' });
      const parsed = { cells: [], metadata: {} };
      api.postForm.mockResolvedValue({ ok: true, status: 200, data: parsed });

      const result = await ChallengeService.parseNotebook(1, file);

      expect(api.postForm).toHaveBeenCalledWith(
        '/challenges/1/parse-notebook',
        expect.any(FormData),
      );
      const fd = api.postForm.mock.calls[0][1];
      expect(fd.get('file')).toBe(file);
      expect(result.data).toEqual(parsed);
    });

    it('handles parse error', async () => {
      const file = new File(['invalid'], 'bad.ipynb', { type: 'application/json' });
      api.postForm.mockResolvedValue({
        ok: false,
        status: 422,
        data: { error: 'Invalid notebook' },
      });

      const result = await ChallengeService.parseNotebook(1, file);

      expect(result.ok).toBe(false);
      expect(result.status).toBe(422);
    });
  });
});
