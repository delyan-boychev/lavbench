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

  describe('put()', () => {
    it('sends PUT with JSON body', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ updated: true }),
      });
      const result = await api.put('/update/1', { title: 'new' });
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/update/1',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ title: 'new' }),
        }),
      );
      expect(result.ok).toBe(true);
    });
  });

  describe('delete()', () => {
    it('sends DELETE request', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 204, json: () => Promise.resolve(null) });
      const result = await api.delete('/remove/1');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/remove/1',
        expect.objectContaining({ method: 'DELETE' }),
      );
      expect(result.ok).toBe(true);
    });
  });

  describe('putForm()', () => {
    it('sends PUT with FormData and no Content-Type', async () => {
      const formData = new FormData();
      formData.append('file', 'content');
      mockFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) });
      await api.putForm('/upload', formData);
      const callArgs = mockFetch.mock.calls[0][1];
      expect(callArgs.method).toBe('PUT');
      expect(callArgs.body).toBe(formData);
      expect(callArgs.headers['Content-Type']).toBeUndefined();
    });
  });

  describe('getBlob()', () => {
    it('fetches blob without JSON parsing', async () => {
      const blob = new Blob(['data']);
      mockFetch.mockResolvedValue({ ok: true, status: 200, blob: () => Promise.resolve(blob) });
      const result = await api.getBlob('/download/file');
      expect(mockFetch).toHaveBeenCalledWith('/api/download/file', expect.any(Object));
      expect(result.ok).toBe(true);
      const resultBlob = await result.blob();
      expect(resultBlob).toBe(blob);
    });

    it('dispatches auth:unauthorized on 401 for blob request', async () => {
      const dispatchFn = vi.spyOn(window, 'dispatchEvent');
      mockFetch.mockResolvedValue({ ok: false, status: 401, json: () => Promise.resolve({}) });
      await api.getBlob('/protected/file');
      expect(dispatchFn).toHaveBeenCalledWith(expect.any(Event));
      expect(dispatchFn.mock.calls[0][0].type).toBe('auth:unauthorized');
    });
  });

  describe('fetch()', () => {
    it('sends custom fetch request with absolute URL', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) });
      await api.fetch('https://external.example.com/data', { method: 'GET' });
      expect(mockFetch).toHaveBeenCalledWith(
        'https://external.example.com/data',
        expect.any(Object),
      );
    });

    it('prefixes relative URL with /api', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) });
      await api.fetch('/custom/endpoint');
      expect(mockFetch).toHaveBeenCalledWith('/api/custom/endpoint', expect.any(Object));
    });

    it('handles 401 in fetch wrapper', async () => {
      const dispatchFn = vi.spyOn(window, 'dispatchEvent');
      mockFetch.mockResolvedValue({ ok: false, status: 401, json: () => Promise.resolve({}) });
      await api.fetch('/custom/endpoint');
      expect(dispatchFn).toHaveBeenCalledWith(expect.any(Event));
      expect(dispatchFn.mock.calls[0][0].type).toBe('auth:unauthorized');
    });
  });

  describe('CSRF retry', () => {
    it('retries on 403 with ERR_CSRF_FAILED code', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: false,
          status: 403,
          json: () => Promise.resolve({ code: 'ERR_CSRF_FAILED' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ csrf_token: 'new-token' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ success: true }),
        });

      const result = await api.post('/retry-test', { data: 1 });

      expect(mockFetch).toHaveBeenCalledTimes(3);
      expect(result.ok).toBe(true);
      expect(result.data).toEqual({ success: true });
    });

    it('returns original 403 for non-CSRF errors (no retry)', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 403,
        json: () => Promise.resolve({ code: 'OTHER_ERROR' }),
      });
      const result = await api.post('/no-retry', { data: 1 });
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(result.ok).toBe(false);
      expect(result.status).toBe(403);
    });
  });

  describe('edge cases', () => {
    it('handles 204 No Content response', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 204,
        json: () => {
          throw new Error('No content');
        },
      });
      const result = await api.delete('/remove/1');
      expect(result.ok).toBe(true);
      expect(result.data).toBeNull();
    });

    it('handles JSON parse failure gracefully', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.reject(new Error('Invalid JSON')),
      });
      const result = await api.get('/bad-json');
      expect(result.ok).toBe(true);
      expect(result.data).toBeNull();
    });
  });
});
