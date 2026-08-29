export class ApiRequestError extends Error {
  constructor(result) {
    const data = result?.data;
    const message = data?.error || `Request failed${result?.status ? ` (${result.status})` : ''}`;
    super(message);
    this.name = 'ApiRequestError';
    this.code = data?.code;
    this.error = data?.error || message;
    this.status = result?.status;
    this.data = data;
  }
}

export function requireOk(result) {
  if (!result?.ok) throw new ApiRequestError(result);
  return result;
}
