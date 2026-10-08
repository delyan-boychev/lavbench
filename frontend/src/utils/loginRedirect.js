const DEFAULT_REDIRECT = '/challenges';

/**
 * Resolve the post-login destination from router state, allowing only in-app paths.
 *
 * @param {unknown} from
 * @returns {string}
 */
export function resolveLoginRedirect(from) {
  if (!from || typeof from !== 'object') return DEFAULT_REDIRECT;
  const { pathname, search = '', hash = '' } = /** @type {Record<string, unknown>} */ (from);
  if (typeof pathname !== 'string' || typeof search !== 'string' || typeof hash !== 'string') {
    return DEFAULT_REDIRECT;
  }
  // Reject protocol-relative or backslash paths that a browser could treat as another origin
  if (!pathname.startsWith('/') || pathname.startsWith('//') || pathname.includes('\\')) {
    return DEFAULT_REDIRECT;
  }
  if (pathname === '/login' || pathname.startsWith('/login/')) return DEFAULT_REDIRECT;
  return `${pathname}${search}${hash}`;
}
