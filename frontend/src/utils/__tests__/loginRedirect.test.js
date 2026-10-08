import { describe, it, expect } from 'vitest';
import { resolveLoginRedirect } from '../loginRedirect';

describe('resolveLoginRedirect', () => {
  it('keeps in-app paths with search and hash', () => {
    expect(resolveLoginRedirect({ pathname: '/admin', search: '?tab=users', hash: '#x' })).toBe(
      '/admin?tab=users#x',
    );
  });

  it('falls back to /challenges for missing or unsafe targets', () => {
    expect(resolveLoginRedirect(undefined)).toBe('/challenges');
    expect(resolveLoginRedirect('/admin')).toBe('/challenges');
    expect(resolveLoginRedirect({ pathname: 'https://evil.example.com' })).toBe('/challenges');
    expect(resolveLoginRedirect({ pathname: '//evil.example.com' })).toBe('/challenges');
    expect(resolveLoginRedirect({ pathname: '/\\evil.example.com' })).toBe('/challenges');
    expect(resolveLoginRedirect({ pathname: '/login' })).toBe('/challenges');
  });
});
