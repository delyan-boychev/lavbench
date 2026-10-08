export const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Combine a caller's AbortSignal with a timeout, degrading gracefully where
 * AbortSignal.timeout/any are unavailable (older browsers, some test DOMs).
 * @param {AbortSignal | undefined} signal
 * @param {number} timeoutMs
 * @returns {AbortSignal | undefined}
 */
export function withTimeout(signal, timeoutMs) {
  if (
    !timeoutMs ||
    typeof AbortSignal === 'undefined' ||
    typeof AbortSignal.timeout !== 'function'
  ) {
    return signal;
  }
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  if (!signal) return timeoutSignal;
  return typeof AbortSignal.any === 'function' ? AbortSignal.any([signal, timeoutSignal]) : signal;
}

/**
 * @typedef {{ signal?: AbortSignal, timeoutMs?: number }} RequestOptions
 */

class ApiService {
  #baseUrl;
  #csrfToken;
  /** @type {Promise<void> | null} */
  #csrfRefresh = null;

  constructor(baseUrl = '/api') {
    this.#baseUrl = baseUrl;
    this.#csrfToken = null;
  }

  /**
   * Fetch a CSRF token from the server and cache it. Concurrent callers share one
   * in-flight request so parallel 403 retries do not race each other.
   * @returns {Promise<void>}
   */
  refreshCsrfToken() {
    if (!this.#csrfRefresh) {
      this.#csrfRefresh = (async () => {
        try {
          const res = await fetch(`${this.#baseUrl}/auth/csrf-token`);
          if (res.ok) {
            const data = await res.json();
            this.#csrfToken = data.csrf_token;
          }
        } catch {
          // CSRF failure is non-fatal; mutations without it will get 403
        }
      })().finally(() => {
        this.#csrfRefresh = null;
      });
    }
    return this.#csrfRefresh;
  }

  #getHeaders(isForm = false, method = 'GET') {
    /** @type {{ [key: string]: string }} */
    const headers = {};
    if (!isForm) headers['Content-Type'] = 'application/json';
    // Attach CSRF token for state-changing requests
    if (this.#csrfToken && method !== 'GET' && method !== 'HEAD') {
      headers['X-CSRF-Token'] = this.#csrfToken;
    }
    return headers;
  }

  async #handleResponse(res) {
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    const data = res.status === 204 ? null : await res.json().catch(() => null);
    return { ok: res.ok, status: res.status, data, res };
  }

  /**
   * @param {string} method
   * @param {string} path
   * @param {any} body
   * @param {boolean} [isForm]
   * @param {RequestOptions} [options]
   */
  async #csrfAwareRequest(method, path, body, isForm = false, options = {}) {
    // Mutations get no default timeout: admin actions like finalize or a forced
    // backup can legitimately run long, and aborting them hides the outcome
    const { signal, timeoutMs = 0 } = options;
    const send = () =>
      fetch(`${this.#baseUrl}${path}`, {
        method,
        headers: this.#getHeaders(isForm, method),
        body,
        signal: withTimeout(signal, timeoutMs),
      });
    const result = await this.#handleResponse(await send());
    if (result.status === 403 && result.data?.code === 'ERR_CSRF_FAILED') {
      await this.refreshCsrfToken();
      return this.#handleResponse(await send());
    }
    return result;
  }

  // Generic fetch wrapper to act as a drop-in replacement for native fetch. It is used for
  // streamed downloads, so it applies no default timeout; callers may pass their own signal
  async fetch(url, options = {}) {
    const isForm = options.body instanceof FormData;
    const method = options.method || 'GET';
    const defaultHeaders = this.#getHeaders(isForm, method);

    const mergedHeaders = { ...defaultHeaders, ...options.headers };
    if (isForm && mergedHeaders['Content-Type']) {
      delete mergedHeaders['Content-Type'];
    }

    let finalUrl = url;
    if (!url.startsWith('http')) {
      finalUrl = url.startsWith(this.#baseUrl) ? url : `${this.#baseUrl}${url}`;
    }

    const res = await fetch(finalUrl, {
      ...options,
      headers: mergedHeaders,
    });

    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return res;
  }

  /**
   * @param {string} path
   * @param {RequestOptions} [options]
   */
  async get(path, options = {}) {
    const { signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(false, 'GET'),
      signal: withTimeout(signal, timeoutMs),
    });
    return this.#handleResponse(res);
  }

  async getBestSubmissions(challengeId, userId) {
    return this.get(`/challenges/${challengeId}/users/${userId}/best-submissions`);
  }

  /**
   * @param {string} path
   * @param {any} [body]
   * @param {RequestOptions} [options]
   */
  async post(path, body, options = {}) {
    return this.#csrfAwareRequest(
      'POST',
      path,
      body !== undefined ? JSON.stringify(body) : undefined,
      false,
      options,
    );
  }

  /**
   * @param {string} path
   * @param {any} [body]
   * @param {RequestOptions} [options]
   */
  async put(path, body, options = {}) {
    return this.#csrfAwareRequest(
      'PUT',
      path,
      body !== undefined ? JSON.stringify(body) : undefined,
      false,
      options,
    );
  }

  /**
   * @param {string} path
   * @param {RequestOptions} [options]
   */
  async delete(path, options = {}) {
    return this.#csrfAwareRequest('DELETE', path, undefined, false, options);
  }

  /**
   * @param {string} path
   * @param {FormData} formData
   * @param {{ signal?: AbortSignal }} [options]
   */
  async postForm(path, formData, options = {}) {
    return this.#csrfAwareRequest('POST', path, formData, true, {
      signal: options.signal,
      timeoutMs: 0,
    });
  }

  /**
   * @param {string} path
   * @param {FormData} formData
   * @param {{ signal?: AbortSignal }} [options]
   */
  async putForm(path, formData, options = {}) {
    return this.#csrfAwareRequest('PUT', path, formData, true, {
      signal: options.signal,
      timeoutMs: 0,
    });
  }

  /**
   * @param {string} path
   * @param {{ signal?: AbortSignal }} [options]
   */
  async getBlob(path, options = {}) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(false, 'GET'),
      signal: options.signal,
    });
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return res;
  }
}

export default new ApiService();
