import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiRequestError } from '../apiResult';

vi.mock('../ApiService.js', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

import EnvironmentService from '../EnvironmentService';
import api from '../ApiService.js';

describe('EnvironmentService', () => {
  beforeEach(() => vi.clearAllMocks());

  it('addresses the stage environment, or the competition one without a stage', () => {
    EnvironmentService.get('c1', 's1');
    EnvironmentService.get('c1', null);
    EnvironmentService.save('c1', 's1', { enabled: true });
    EnvironmentService.save('c1', null, { enabled: false });
    expect(api.get).toHaveBeenNthCalledWith(1, '/challenges/c1/stages/s1/environment');
    expect(api.get).toHaveBeenNthCalledWith(2, '/challenges/c1/environment');
    expect(api.put).toHaveBeenNthCalledWith(1, '/challenges/c1/stages/s1/environment', {
      enabled: true,
    });
    expect(api.put).toHaveBeenNthCalledWith(2, '/challenges/c1/environment', { enabled: false });
  });

  it('calls the environment actions and the student routes', () => {
    EnvironmentService.getImages('c1');
    EnvironmentService.publish('c1', 'e1');
    EnvironmentService.extend('c1', 'e1', { end_time: 'x', reason: 'y' });
    EnvironmentService.getWorkspaces('c1', 'e1');
    EnvironmentService.getForTask('t1');
    EnvironmentService.launch('t1');
    expect(api.get).toHaveBeenCalledWith('/challenges/c1/environment/images');
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
