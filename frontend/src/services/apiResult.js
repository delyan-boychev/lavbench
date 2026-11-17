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
    const retryAfter = Number(result?.res?.headers?.get?.('Retry-After'));
    this.retryAfter = retryAfter > 0 ? retryAfter : null;
  }
}

export function requireOk(result) {
  if (!result?.ok) throw new ApiRequestError(result);
  return result;
}

/**
 * React Query retry rule: a 4xx answer (locked, forbidden, not found) is the same on every
 * attempt, so only network and server failures get the one retry the app default allows
 * @param {number} failureCount
 * @param {unknown} error
 */
export function retryUnlessClientError(failureCount, error) {
  const status = /** @type {{ status?: number } | null} */ (error)?.status;
  if (typeof status === 'number' && status >= 400 && status < 500) return false;
  return failureCount < 1;
}
