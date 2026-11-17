import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiRequestError } from '../apiResult';

vi.mock('../ApiService.js', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

import EnvironmentService from '../EnvironmentService';
import api from '../ApiService.js';

describe('EnvironmentService', () => {
  beforeEach(() => vi.clearAllMocks());

  it('lists the environments of a competition and reads the catalog', () => {
    EnvironmentService.list('c1');
    EnvironmentService.getCatalog();
    expect(api.get).toHaveBeenNthCalledWith(1, '/challenges/c1/environments');
    expect(api.get).toHaveBeenNthCalledWith(2, '/environment/images');
  });

  it('calls the environment actions and the student routes', () => {
    EnvironmentService.publish('c1', 'e1');
    EnvironmentService.extend('c1', 'e1', { end_time: 'x', reason: 'y' });
    EnvironmentService.getWorkspaces('c1', 'e1');
    EnvironmentService.getForTask('t1');
    EnvironmentService.launch('t1');
    expect(api.post).toHaveBeenCalledWith('/challenges/c1/environments/e1/publish');
    expect(api.post).toHaveBeenCalledWith('/challenges/c1/environments/e1/extension', {
      end_time: 'x',
      reason: 'y',
    });
    expect(api.get).toHaveBeenCalledWith('/challenges/c1/environments/e1/workspaces');
    expect(api.get).toHaveBeenCalledWith('/tasks/t1/environment');
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/environment/launch');
    expect(EnvironmentService.liveUrl('c1')).toBe('/api/challenges/c1/environment/live');
  });
});

describe('ApiRequestError', () => {
  it('keeps the Retry-After seconds of a refused request', () => {
    const error = new ApiRequestError({
      ok: false,
      status: 503,
      data: { code: 'ERR_ENVIRONMENT_PREPARING' },
      res: { headers: new Headers({ 'Retry-After': '30' }) },
    });
    expect(error.retryAfter).toBe(30);
    expect(new ApiRequestError({ ok: false, status: 500, data: null }).retryAfter).toBeNull();
  });
});
