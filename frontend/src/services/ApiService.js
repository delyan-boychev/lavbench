// Base API service class — all methods read the JWT from localStorage on every call
class ApiService {
  #baseUrl;

  constructor(baseUrl = '/api') {
    this.#baseUrl = baseUrl;
  }

  #getHeaders(isForm = false) {
    const token = localStorage.getItem('token');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (!isForm) headers['Content-Type'] = 'application/json';
    return headers;
  }

  async get(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(),
    });
    const data = res.status === 204 ? null : await res.json();
    return { ok: res.ok, status: res.status, data };
  }

  async post(path, body) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'POST',
      headers: this.#getHeaders(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = res.status === 204 ? null : await res.json();
    return { ok: res.ok, status: res.status, data };
  }

  async put(path, body) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'PUT',
      headers: this.#getHeaders(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = res.status === 204 ? null : await res.json();
    return { ok: res.ok, status: res.status, data };
  }

  async delete(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'DELETE',
      headers: this.#getHeaders(),
    });
    const data = res.status === 204 ? null : await res.json();
    return { ok: res.ok, status: res.status, data };
  }

  async postForm(path, formData) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'POST',
      headers: this.#getHeaders(true),
      body: formData,
    });
    const data = res.status === 204 ? null : await res.json();
    return { ok: res.ok, status: res.status, data };
  }

  async putForm(path, formData) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      method: 'PUT',
      headers: this.#getHeaders(true),
      body: formData,
    });
    const data = res.status === 204 ? null : await res.json();
    return { ok: res.ok, status: res.status, data };
  }

  // Returns a raw fetch response (for streaming blob downloads)
  async getBlob(path) {
    const res = await fetch(`${this.#baseUrl}${path}`, {
      headers: this.#getHeaders(),
    });
    return res;
  }
}

export default new ApiService();
