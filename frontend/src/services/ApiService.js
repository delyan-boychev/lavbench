class ApiService {
  #baseUrl;

  constructor(baseUrl = '/api') {
    this.#baseUrl = baseUrl;
  }

  #getHeaders(isForm = false) {
    /** @type {{ [key: string]: string }} */
    const headers = {};
    if (!isForm) headers['Content-Type'] = 'application/json';
    return headers;
  }

  async #handleResponse(res) {
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    const data = res.status === 204 ? null : await res.json().catch(() => null);
    return { ok: res.ok, status: res.status, data, res };
  }

  // Generic fetch wrapper to act as a drop-in replacement for native fetch
  async fetch(url, options = {}) {
    const isForm = options.body instanceof FormData;
    const defaultHeaders = this.#getHeaders(isForm);
    
    // We strip headers that fetch would auto-generate for FormData
    const mergedHeaders = { ...defaultHeaders, ...options.headers };
    if (isForm && mergedHeaders['Content-Type']) {
      delete mergedHeaders['Content-Type'];
    }

    let finalUrl = url;
    if (!url.startsWith('http')) {
      // Avoid double /api prefix
      finalUrl = url.startsWith(this.#baseUrl) ? url : `${this.#baseUrl}${url}`;
    }

    const res = await fetch(finalUrl, {
      ...options,
      headers: mergedHeaders
    });

    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return res;
  }

  async get(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(),
    });
    return this.#handleResponse(res);
  }

  async post(path, body) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'POST',
      headers: this.#getHeaders(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return this.#handleResponse(res);
  }

  async put(path, body) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'PUT',
      headers: this.#getHeaders(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return this.#handleResponse(res);
  }

  async delete(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'DELETE',
      headers: this.#getHeaders(),
    });
    return this.#handleResponse(res);
  }

  async postForm(path, formData) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'POST',
      headers: this.#getHeaders(true),
      body: formData,
    });
    return this.#handleResponse(res);
  }

  async putForm(path, formData) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'PUT',
      headers: this.#getHeaders(true),
      body: formData,
    });
    return this.#handleResponse(res);
  }

  async getBlob(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(),
    });
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return res;
  }
}

export default new ApiService();
