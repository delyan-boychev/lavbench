import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import EnvironmentStatus from '../EnvironmentStatus';

const status = (overrides) => ({
  state: 'off',
  published: false,
  progress: null,
  since: null,
  alert: false,
  code: null,
  message: null,
  limit: null,
  ...overrides,
});

describe('EnvironmentStatus', () => {
  afterEach(() => vi.useRealTimers());

  it.each([
    ['off', 'Off'],
    ['uploading', 'Uploading'],
    ['preparing', 'Preparing'],
    ['ready', 'Ready'],
  ])('labels the %s state', (state, text) => {
    render(<EnvironmentStatus status={status({ state })} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it('shows the upload progress', () => {
    render(<EnvironmentStatus status={status({ state: 'uploading', progress: 40 })} />);
    expect(screen.getByText('Uploading 40%')).toBeInTheDocument();
  });

  it('says how long it has been preparing and raises the alert', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2027-05-01T10:12:00Z'));
    render(
      <EnvironmentStatus
        status={status({ state: 'preparing', since: '2027-05-01T10:00:00Z', alert: true })}
      />,
    );
    expect(screen.getByText('Preparing for 12 min')).toBeInTheDocument();
    expect(
      screen.getByText('Preparing is taking longer than expected. Check nanoColab.'),
    ).toBeInTheDocument();
  });

  it("translates the problem code with its limit without repeating LavBench's message", () => {
    render(
      <EnvironmentStatus
        status={status({
          state: 'problem',
          code: 'ERR_ENVIRONMENT_PACKAGE_TOO_LARGE',
          limit: '2 GiB',
          message: 'The package would be larger than 2 GiB.',
        })}
      />,
    );
    expect(screen.getByText('Problem')).toBeInTheDocument();
    expect(
      screen.getByText('The workspace package is too large (limit 2 GiB).'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Details:/)).not.toBeInTheDocument();
  });

  it("keeps nanoColab's own message as details for admins", () => {
    render(
      <EnvironmentStatus
        status={status({
          state: 'problem',
          code: 'ERR_ENVIRONMENT_SYNC_FAILED',
          message: 'Asset lb-123 is not ready',
        })}
      />,
    );
    expect(screen.getByText('Details: Asset lb-123 is not ready')).toBeInTheDocument();
  });

  it('gives the jury the translated code without the message', () => {
    render(
      <EnvironmentStatus
        status={status({ state: 'problem', code: 'ERR_ENVIRONMENT_SYNC_FAILED' })}
      />,
    );
    expect(
      screen.getByText('The workspaces could not be synchronised with nanoColab.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Details:/)).not.toBeInTheDocument();
  });

  it("shows nanoColab's message for a blocked start without a code", () => {
    render(
      <EnvironmentStatus status={status({ state: 'problem', message: 'Image pull failed' })} />,
    );
    expect(screen.getByText('Image pull failed')).toBeInTheDocument();
  });

  it('says how old the last status is', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2027-05-01T10:00:20Z'));
    const { rerender } = render(
      <EnvironmentStatus status={status({ state: 'ready', fetched_at: '2027-05-01T10:00:00Z' })} />,
    );
    expect(screen.getByText('Checked 20 seconds ago')).toBeInTheDocument();
    rerender(
      <EnvironmentStatus
        status={status({ state: 'unknown', fetched_at: '2027-05-01T09:55:20Z' })}
      />,
    );
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.getByText('Last update 5 minutes ago')).toBeInTheDocument();
  });

  it('shows no age before the first status check', () => {
    render(<EnvironmentStatus status={status({ state: 'unknown' })} />);
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.queryByText(/Checked|Last update/)).not.toBeInTheDocument();
  });
});
