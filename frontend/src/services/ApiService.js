class ApiService {
  #baseUrl;
  #csrfToken;

  constructor(baseUrl = '/api') {
    this.#baseUrl = baseUrl;
    this.#csrfToken = null;
  }

  /** Fetch a CSRF token from the server and cache it. */
  async refreshCsrfToken() {
    try {
      const res = await fetch(`${this.#baseUrl}/auth/csrf-token`);
      if (res.ok) {
        const data = await res.json();
        this.#csrfToken = data.csrf_token;
      }
    } catch {
      // CSRF failure is non-fatal; mutations without it will get 403
    }
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

  async #csrfAwareRequest(method, path, body, isForm = false) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method,
      headers: this.#getHeaders(isForm, method),
      body,
    });
    const result = await this.#handleResponse(res);
    if (result.status === 403 && result.data?.code === 'ERR_CSRF_FAILED') {
      await this.refreshCsrfToken();
      const retryRes = await fetch(`${this.#baseUrl}${path}`, {
        method,
        headers: this.#getHeaders(isForm, method),
        body,
      });
      return this.#handleResponse(retryRes);
    }
    return result;
  }

  // Generic fetch wrapper to act as a drop-in replacement for native fetch
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

  async get(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(false, 'GET'),
    });
    return this.#handleResponse(res);
  }

  async post(path, body) {
    return this.#csrfAwareRequest(
      'POST',
      path,
      body !== undefined ? JSON.stringify(body) : undefined,
    );
  }

  async put(path, body) {
    return this.#csrfAwareRequest(
      'PUT',
      path,
      body !== undefined ? JSON.stringify(body) : undefined,
    );
  }

  async delete(path) {
    return this.#csrfAwareRequest('DELETE', path);
  }

  async postForm(path, formData) {
    return this.#csrfAwareRequest('POST', path, formData, true);
  }

  async putForm(path, formData) {
    return this.#csrfAwareRequest('PUT', path, formData, true);
  }

  async getBlob(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(false, 'GET'),
    });
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return res;
  }
}

export default new ApiService();
