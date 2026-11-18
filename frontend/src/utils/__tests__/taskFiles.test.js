import { describe, it, expect } from 'vitest';
import { parseTaskFiles, storedVisibility, uploadVisibility } from '../taskFiles';

describe('taskFiles', () => {
  it('reads files sent as a list or as JSON text', () => {
    expect(parseTaskFiles([{ filename: 'a' }])).toEqual([{ filename: 'a' }]);
    expect(parseTaskFiles('[{"filename":"a"}]')).toEqual([{ filename: 'a' }]);
    expect(parseTaskFiles('not json')).toEqual([]);
    expect(parseTaskFiles(null)).toEqual([]);
  });

  it('keeps labels and the baseline submission hidden whatever the zone', () => {
    expect(uploadVisibility('labels.parquet', 'public')).toBe('hidden');
    expect(uploadVisibility('baseline_submission.parquet', 'public')).toBe('hidden');
    expect(uploadVisibility('train.csv', 'public')).toBe('public');
    expect(uploadVisibility('extra.csv', 'hidden')).toBe('hidden');
  });

  it('follows the visibility the API reports', () => {
    expect(storedVisibility({ filename: 'notes.txt', visibility: 'hidden' })).toBe('hidden');
    expect(storedVisibility({ filename: 'labels.parquet' })).toBe('hidden');
    expect(storedVisibility({ filename: 'train.csv' })).toBe('public');
  });
});
