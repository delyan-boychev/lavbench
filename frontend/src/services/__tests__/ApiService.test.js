import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('ApiService', () => {
  let api;
  let mockFetch;

  beforeEach(async () => {
    mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);
    vi.stubGlobal(
      'CustomEvent',
      class extends Event {
        constructor(type, init) {
          super(type, init);
          Object.assign(this, init?.detail || {});
        }
      },
    );
    const mod = await import('../../services/ApiService');
    api = mod.default;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('get()', () => {
    it('sends a GET request with correct URL prefix', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ data: 'test' }),
      });
      await api.get('/test');
      expect(mockFetch).toHaveBeenCalledWith('/api/test', expect.any(Object));
    });

    it('returns structured response with ok, status, data', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ result: 42 }),
      });
      const result = await api.get('/test');
      expect(result).toEqual({
        ok: true,
        status: 200,
        data: { result: 42 },
        res: expect.any(Object),
      });
    });
  });

  describe('post()', () => {
    it('sends POST with JSON body', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 201,
        json: () => Promise.resolve({ id: 1 }),
      });
      const result = await api.post('/create', { name: 'test' });
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/create',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ name: 'test' }),
        }),
      );
      expect(result.ok).toBe(true);
    });

    it('handles POST with undefined body', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) });
      await api.post('/action');
      const callArgs = mockFetch.mock.calls[0][1];
      expect(callArgs.body).toBeUndefined();
    });
  });

  describe('401 handling', () => {
    it('dispatches auth:unauthorized event on 401 response', async () => {
      const dispatchFn = vi.spyOn(window, 'dispatchEvent');
      mockFetch.mockResolvedValue({ ok: false, status: 401, json: () => Promise.resolve({}) });
      await api.get('/protected');
      expect(dispatchFn).toHaveBeenCalledWith(expect.any(Event));
      const event = dispatchFn.mock.calls[0][0];
      expect(event.type).toBe('auth:unauthorized');
    });
  });

  describe('postForm()', () => {
    it('sends POST with FormData and no Content-Type', async () => {
      const formData = new FormData();
      formData.append('file', 'content');
      mockFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) });
      await api.postForm('/upload', formData);
      const callArgs = mockFetch.mock.calls[0][1];
      expect(callArgs.method).toBe('POST');
      expect(callArgs.body).toBe(formData);
      expect(callArgs.headers['Content-Type']).toBeUndefined();
    });
  });
});
