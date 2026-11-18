import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../ApiService';
import { uploadWithProgress } from '../upload';
import { ApiRequestError, requireOk } from '../apiResult';

vi.mock('../ApiService', () => ({
  default: { csrfToken: vi.fn(), refreshCsrfToken: vi.fn() },
}));

/** A scripted XMLHttpRequest: each test answers it with respond(), progress() or fail(). */
class FakeXhr {
  /** @type {FakeXhr[]} */
  static instances = [];

  constructor() {
    this.headers = {};
    this.upload = {};
    this.status = 0;
    this.responseText = '';
    this.responseHeaders = {};
    this.withCredentials = false;
    FakeXhr.instances.push(this);
  }

  open(method, url) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name, value) {
    this.headers[name] = value;
  }

  getResponseHeader(name) {
    return this.responseHeaders[name] ?? null;
  }

  send(body) {
    this.body = body;
  }

  abort() {
    this.aborted = true;
    this.onabort?.();
  }

  progress(loaded, total) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }

  respond(status, body, headers = {}) {
    this.status = status;
    this.responseText = typeof body === 'string' ? body : JSON.stringify(body);
    this.responseHeaders = headers;
    this.onload?.();
  }

  fail() {
    this.onerror?.();
  }
}

const zip = new Blob(['PK'], { type: 'application/zip' });

/** The request the helper opened, once its CSRF token has been read. */
async function nextXhr(index = 0) {
  await vi.waitFor(() => expect(FakeXhr.instances.length).toBeGreaterThan(index));
  return FakeXhr.instances[index];
}

describe('uploadWithProgress', () => {
  beforeEach(() => {
    FakeXhr.instances = [];
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    api.csrfToken.mockReset();
    api.csrfToken.mockResolvedValue('token-1');
    api.refreshCsrfToken.mockReset();
    api.refreshCsrfToken.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends the raw body with cookies and the CSRF header, and reports progress', async () => {
    const onProgress = vi.fn();
    const pending = uploadWithProgress('/tasks/t1/hf-zip', zip, {
      contentType: 'application/zip',
      onProgress,
    });
    const xhr = await nextXhr();
    expect(xhr.method).toBe('PUT');
    expect(xhr.url).toBe('/api/tasks/t1/hf-zip');
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.headers['X-CSRF-Token']).toBe('token-1');
    expect(xhr.headers['Content-Type']).toBe('application/zip');
    expect(xhr.body).toBe(zip);

    xhr.progress(25, 100);
    xhr.progress(100, 100);
    xhr.respond(200, { id: 't1', hf_folders: ['models/a/b'] });

    const result = await pending;
    expect(onProgress.mock.calls).toEqual([[0.25], [1]]);
    expect(result).toMatchObject({ ok: true, status: 200, data: { id: 't1' } });
  });

  it('defaults to an octet-stream body', async () => {
    const pending = uploadWithProgress('/x', zip);
    const xhr = await nextXhr();
    expect(xhr.headers['Content-Type']).toBe('application/octet-stream');
    xhr.respond(200, {});
    await pending;
  });

  it('returns a refusal with its code, limit and Retry-After for requireOk', async () => {
    const pending = uploadWithProgress('/tasks/t1/hf-zip', zip);
    const xhr = await nextXhr();
    xhr.respond(
      413,
      { error: 'Too large', code: 'ERR_HF_ZIP_TOO_LARGE', limit: '10 GB' },
      { 'Retry-After': '7' },
    );
    const result = await pending;
    expect(result.ok).toBe(false);
    expect(result.status).toBe(413);

    let error;
    try {
      requireOk(result);
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ApiRequestError);
    expect(error.code).toBe('ERR_HF_ZIP_TOO_LARGE');
    expect(error.data.limit).toBe('10 GB');
    expect(error.retryAfter).toBe(7);
  });

  it('leaves the body empty when a proxy answers with HTML', async () => {
    const pending = uploadWithProgress('/tasks/t1/hf-zip', zip);
    const xhr = await nextXhr();
    xhr.respond(413, '<html>413 Request Entity Too Large</html>');
    expect(await pending).toMatchObject({ ok: false, status: 413, data: null });
  });

  it('rejects with an AbortError and stops the request when the signal aborts', async () => {
    const controller = new AbortController();
    const pending = uploadWithProgress('/tasks/t1/hf-zip', zip, { signal: controller.signal });
    const xhr = await nextXhr();
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(xhr.aborted).toBe(true);
  });

  it('sends nothing when the signal is already aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      uploadWithProgress('/tasks/t1/hf-zip', zip, { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(FakeXhr.instances[0]?.body).toBeUndefined();
  });

  it('rejects with a TypeError when the network fails', async () => {
    const pending = uploadWithProgress('/tasks/t1/hf-zip', zip);
    (await nextXhr()).fail();
    await expect(pending).rejects.toBeInstanceOf(TypeError);
  });

  it('refreshes a rejected CSRF token and sends once more', async () => {
    api.csrfToken.mockResolvedValueOnce('stale').mockResolvedValueOnce('fresh');
    const pending = uploadWithProgress('/tasks/t1/hf-zip', zip);
    const first = await nextXhr(0);
    expect(first.headers['X-CSRF-Token']).toBe('stale');
    first.respond(403, { code: 'ERR_CSRF_FAILED', error: 'CSRF' });

    const second = await nextXhr(1);
    expect(api.refreshCsrfToken).toHaveBeenCalledTimes(1);
    expect(second.headers['X-CSRF-Token']).toBe('fresh');
    second.respond(200, { id: 't1' });
    expect(await pending).toMatchObject({ ok: true });
  });

  it('signals a lost session like the other API calls', async () => {
    const listener = vi.fn();
    window.addEventListener('auth:unauthorized', listener);
    const pending = uploadWithProgress('/tasks/t1/hf-zip', zip);
    (await nextXhr()).respond(401, { code: 'ERR_UNAUTHORIZED' });
    await pending;
    window.removeEventListener('auth:unauthorized', listener);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
