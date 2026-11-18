import { describe, it, expect } from 'vitest';
import {
  diskSummary,
  withCatalogDefaults,
  workspaceDraft,
  workspacePayload,
} from '../workspaceSetting';

const CATALOG = {
  images: [
    { image_id: 'python-base', name: 'Python' },
    { image_id: 'python-ml', name: 'Python ML', default: true },
  ],
  profiles: [{ id: 'cpu-compact', name: 'CPU Compact', cpu_cores: 2, memory_gib: 8 }],
  workspace_gib: { min: 10, max: 98, default: 10 },
};

describe('workspace setting drafts', () => {
  it('starts empty without a setting and fills the catalog defaults', () => {
    const draft = workspaceDraft(null);
    expect(draft).toEqual({
      enabled: false,
      image_id: '',
      profile_id: '',
      workspace_gib: '',
      auto_publish: false,
      archive_until: '',
    });
    expect(withCatalogDefaults(draft, CATALOG)).toMatchObject({
      image_id: 'python-ml',
      profile_id: 'cpu-compact',
      workspace_gib: 10,
    });
  });

  it('keeps stored choices and sends numbers and an empty archive date as null', () => {
    const draft = workspaceDraft({
      enabled: true,
      image_id: 'python-base',
      profile_id: 'cpu-standard',
      workspace_gib: 20,
      auto_publish: true,
      archive_until: '2026-12-01T10:00:00+02:00',
    });
    expect(withCatalogDefaults(draft, CATALOG)).toEqual(draft);
    expect(draft.archive_until).toBe('2026-12-01T10:00');
    expect(workspacePayload({ ...draft, workspace_gib: '25', archive_until: '' })).toEqual({
      enabled: true,
      image_id: 'python-base',
      profile_id: 'cpu-standard',
      workspace_gib: 25,
      auto_publish: true,
      archive_until: null,
    });
  });

  it('sums the disk of the stages that follow the setting, and none once all are published', () => {
    const open = { stage_id: 's1', data_gib: 2, published_at: null };
    const other = { stage_id: 's2', data_gib: 5, published_at: null };
    const done = { stage_id: 's3', data_gib: 1, published_at: '2026-01-01T00:00:00Z' };
    expect(diskSummary([], 10)).toEqual({ disk: '10', published: [] });
    expect(diskSummary([open, other, done], 10)).toEqual({ disk: '12-15', published: [done] });
    expect(diskSummary([done], 10)).toEqual({ disk: null, published: [done] });
  });
});
