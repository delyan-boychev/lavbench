import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import UploadList from '../UploadList';
import { ApiRequestError } from '../../../services/apiResult';

const MB = 1024 * 1024;
let nextId = 1;
const row = (name, status, extra = {}) => ({
  id: nextId++,
  name,
  size: 2 * MB,
  file: new Blob(['x']),
  path: `/tasks/t1/files/${name}`,
  status,
  loaded: 0,
  startedAt: 0,
  error: null,
  retryAt: 0,
  ...extra,
});

const renderList = (items, handlers = {}) =>
  render(
    <UploadList
      items={items}
      onCancel={handlers.onCancel || vi.fn()}
      onRetry={handlers.onRetry || vi.fn()}
    />,
  );

describe('UploadList', () => {
  it('renders nothing without uploads', () => {
    const { container } = renderList([]);
    expect(container).toBeEmptyDOMElement();
  });

  it('sums up the files and bytes done', () => {
    renderList([
      row('a.csv', 'done', { loaded: 2 * MB }),
      row('b.csv', 'uploading', { loaded: MB }),
      row('c.csv', 'waiting'),
    ]);
    expect(screen.getByTestId('upload-overall')).toHaveTextContent('1 of 3 files, 3 MB of 6 MB');
  });

  it('shows each state, with Cancel only while a file waits or uploads', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const waiting = row('w.csv', 'waiting');
    renderList(
      [
        waiting,
        row('u.csv', 'uploading', { loaded: MB, startedAt: Date.now() }),
        row('k.csv', 'checking', { loaded: 2 * MB }),
        row('d.csv', 'done', { loaded: 2 * MB }),
      ],
      { onCancel },
    );
    expect(screen.getByTestId('upload-row-w.csv')).toHaveTextContent('Waiting');
    expect(screen.getByTestId('upload-row-u.csv')).toHaveTextContent('Uploading');
    expect(screen.getByTestId('upload-row-k.csv')).toHaveTextContent('Checking');
    expect(screen.getByTestId('upload-row-d.csv')).toHaveTextContent('Done');
    expect(
      within(screen.getByTestId('upload-row-k.csv')).queryByRole('button'),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId('upload-row-d.csv')).queryByRole('button'),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cancel the upload of w.csv' }));
    expect(onCancel).toHaveBeenCalledWith(waiting.id);
  });

  it('shows the percent and the time left of the running file', () => {
    const now = Date.now();
    vi.spyOn(Date, 'now').mockReturnValue(now);
    renderList([row('u.csv', 'uploading', { loaded: MB / 2, startedAt: now - 10_000 })]);
    const bar = screen.getByRole('progressbar', { name: 'u.csv' });
    expect(bar).toHaveAttribute('aria-valuenow', '25');
    // A quarter took 10 s, so three quarters take 30 s more
    expect(screen.getByTestId('upload-row-u.csv')).toHaveTextContent('30 sec left');
    vi.restoreAllMocks();
  });

  it('gives the reason of a refusal, with its limit, and a Retry', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const error = new ApiRequestError({
      status: 413,
      data: { code: 'ERR_ENVIRONMENT_PACKAGE_TOO_LARGE', error: 'too large', limit: '10 GB' },
    });
    const failed = row('big.csv', 'failed', { error });
    renderList([failed, row('net.csv', 'failed'), row('c.csv', 'cancelled')], { onRetry });

    expect(screen.getByTestId('upload-row-big.csv')).toHaveTextContent(
      'The environment package is too large (limit 10 GB).',
    );
    expect(screen.getByTestId('upload-row-net.csv')).toHaveTextContent(
      'The file could not be uploaded.',
    );
    expect(screen.getByTestId('upload-row-c.csv')).toHaveTextContent('Cancelled');
    await user.click(screen.getByRole('button', { name: 'Upload big.csv again' }));
    expect(onRetry).toHaveBeenCalledWith(failed.id);
    expect(screen.getByRole('button', { name: 'Upload c.csv again' })).toBeEnabled();
  });

  it('holds Retry back while the server asks to wait', () => {
    renderList([row('labels.parquet', 'failed', { retryAt: Date.now() + 5000 })]);
    expect(screen.getByRole('button', { name: 'Upload labels.parquet again' })).toBeDisabled();
    expect(screen.getByText('Try again in 5 seconds.')).toBeInTheDocument();
  });
});
