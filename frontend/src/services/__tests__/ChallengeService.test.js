import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../ApiService.js', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    postForm: vi.fn(),
    getBlob: vi.fn(),
  },
}));

import ChallengeService from '../ChallengeService';
import api from '../ApiService.js';

describe('ChallengeService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  describe('downloadSubmission', () => {
    it('downloads a submission as blob', async () => {
      const blob = new Blob(['content']);
      api.getBlob.mockResolvedValue({ ok: true, status: 200, data: blob });

      const result = await ChallengeService.downloadSubmission(1, 10, 101);

      expect(api.getBlob).toHaveBeenCalledWith('/challenges/1/tasks/10/users/101/download');
      expect(result.data).toBe(blob);
    });
  });

  describe('downloadAuditLogs', () => {
    it('downloads audit logs as blob', async () => {
      const blob = new Blob(['log content']);
      api.getBlob.mockResolvedValue({ ok: true, status: 200, data: blob });

      const result = await ChallengeService.downloadAuditLogs(1);

      expect(api.getBlob).toHaveBeenCalledWith('/challenges/1/audit-logs/download');
      expect(result.data).toBe(blob);
    });
  });
});
