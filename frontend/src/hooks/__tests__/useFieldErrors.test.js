import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useFieldErrors } from '../useFieldErrors';
import { ApiRequestError } from '../../services/apiResult';

const sizeError = new ApiRequestError({
  ok: false,
  status: 422,
  data: {
    code: 'ERR_INVALID_WORKSPACE_SIZE',
    error: 'workspace → workspace_gib: Storage per student must be between 10 and 98 GiB.',
    field: 'workspace.workspace_gib',
    min: 10,
    max: 98,
  },
});

describe('useFieldErrors', () => {
  it('puts a translated message under the named field', () => {
    const { result } = renderHook(() => useFieldErrors('workspace.'));
    let captured;
    act(() => {
      captured = result.current.capture(sizeError);
    });
    expect(captured).toBe(true);
    expect(result.current.errors).toEqual({
      workspace_gib: 'Storage per student must be between 10 and 98 GiB.',
    });
    act(() => result.current.clear('workspace_gib'));
    expect(result.current.errors).toEqual({});
  });

  it('leaves errors without a field of this form to the caller', () => {
    const { result } = renderHook(() => useFieldErrors('workspace.'));
    let captured;
    act(() => {
      captured = result.current.capture({ code: 'ERR_VALIDATION', error: 'bad' });
    });
    expect(captured).toBe(false);
    act(() => {
      captured = result.current.capture({ code: 'ERR_X', error: 'x', field: 'title' });
    });
    expect(captured).toBe(false);
    expect(result.current.errors).toEqual({});
  });

  it('takes per-field messages from client-side checks', () => {
    const { result } = renderHook(() => useFieldErrors());
    act(() => result.current.setErrors({ email: 'Please enter a valid email address' }));
    expect(result.current.errors).toEqual({ email: 'Please enter a valid email address' });
    act(() => result.current.reset());
    expect(result.current.errors).toEqual({});
  });
});
