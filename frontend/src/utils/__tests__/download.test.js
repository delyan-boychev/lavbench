import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { downloadName, saveBlob } from '../download';

describe('saveBlob', () => {
  let createSpy;
  let revokeSpy;

  beforeEach(() => {
    vi.useFakeTimers();
    createSpy = vi.fn().mockReturnValue('blob:mock-url');
    revokeSpy = vi.fn();
    window.URL.createObjectURL = createSpy;
    window.URL.revokeObjectURL = revokeSpy;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('clicks a temporary anchor with the filename and revokes the object URL afterwards', () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const blob = new Blob(['hello'], { type: 'text/plain' });

    saveBlob(blob, 'report.csv');

    expect(createSpy).toHaveBeenCalledWith(blob);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    const anchor = clickSpy.mock.contexts[0];
    expect(anchor.getAttribute('download')).toBe('report.csv');
    expect(anchor.getAttribute('href')).toBe('blob:mock-url');
    expect(document.body.contains(anchor)).toBe(false);

    expect(revokeSpy).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revokeSpy).toHaveBeenCalledWith('blob:mock-url');
  });
});

describe('downloadName', () => {
  const response = (value) =>
    /** @type {any} */ ({ headers: new Headers(value ? { 'Content-Disposition': value } : {}) });

  it('uses the name the server set', () => {
    expect(downloadName(response('attachment; filename="Owl_task_sub_1.parquet"'), 'x')).toBe(
      'Owl_task_sub_1.parquet',
    );
  });

  it('falls back without a header', () => {
    expect(downloadName(response(''), 'fallback.ipynb')).toBe('fallback.ipynb');
  });
});
