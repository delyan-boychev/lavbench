import api from './ApiService.js';

/**
 * @typedef {{
 *   method?: string,
 *   contentType?: string,
 *   onProgress?: (fraction: number) => void,
 *   signal?: AbortSignal,
 * }} UploadOptions
 */

/** The error a cancelled upload rejects with, named like fetch's. */
function abortError() {
  return new DOMException('The upload was cancelled.', 'AbortError');
}

/**
 * @param {string} path
 * @param {Blob} body
 * @param {UploadOptions} options
 * @param {string | null} csrf
 * @returns {Promise<{ ok: boolean, status: number, data: any, res: { headers: { get: (name: string) => string | null } } }>}
 */
function send(path, body, options, csrf) {
  const { method = 'PUT', contentType, onProgress, signal } = options;
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const xhr = new XMLHttpRequest();
    const onAbort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener('abort', onAbort);
    xhr.open(method, `/api${path}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type', contentType || 'application/octet-stream');
    if (csrf) xhr.setRequestHeader('X-CSRF-Token', csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(event.loaded / event.total);
    };
    xhr.onload = () => {
      cleanup();
      if (xhr.status === 401) window.dispatchEvent(new CustomEvent('auth:unauthorized'));
      let data = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        // A proxy's HTML error page carries no code; the caller shows its fallback
      }
      resolve({
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        data,
        res: { headers: { get: (name) => xhr.getResponseHeader(name) } },
      });
    };
    xhr.onerror = () => {
      cleanup();
      reject(new TypeError('The upload failed: network error.'));
    };
    xhr.onabort = () => {
      cleanup();
      reject(abortError());
    };
    signal?.addEventListener('abort', onAbort, { once: true });
    xhr.send(body);
  });
}

/**
 * Send a file as the raw request body, reporting upload progress (fetch cannot).
 * Resolves like ApiService calls ({ ok, status, data, res }); rejects with an AbortError
 * when the signal aborts and with a TypeError when the network fails.
 * @param {string} path the API path after /api
 * @param {Blob} body
 * @param {UploadOptions} [options]
 */
export async function uploadWithProgress(path, body, options = {}) {
  const result = await send(path, body, options, await api.csrfToken());
  if (result.status === 403 && result.data?.code === 'ERR_CSRF_FAILED') {
    await api.refreshCsrfToken();
    return send(path, body, options, await api.csrfToken());
  }
  return result;
}
