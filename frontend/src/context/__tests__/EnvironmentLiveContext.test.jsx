import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '../../test-utils';
import {
  EnvironmentLiveProvider,
  useEnvironmentLiveInterval,
  useEnvironmentLiveSubscription,
} from '../EnvironmentLiveContext';

const streams = { opened: [], closed: [], interval: false };

vi.mock('../../hooks/useSSEInvalidation', async () => {
  const { useEffect } = await import('react');
  function useStreamDouble(url) {
    useEffect(() => {
      streams.opened.push(url);
      return () => streams.closed.push(url);
    }, [url]);
    return { connected: !streams.interval, refetchInterval: streams.interval };
  }
  return { default: useStreamDouble };
});

function Consumer({ challengeId, active = true }) {
  useEnvironmentLiveSubscription(challengeId, active);
  const interval = useEnvironmentLiveInterval(challengeId);
  return <span data-testid={`interval-${challengeId}`}>{String(interval)}</span>;
}

function renderConsumers(consumers) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <EnvironmentLiveProvider>{consumers}</EnvironmentLiveProvider>
    </QueryClientProvider>,
  );
}

describe('EnvironmentLiveProvider', () => {
  beforeEach(() => {
    streams.opened = [];
    streams.closed = [];
    streams.interval = false;
  });

  it('opens one stream per competition however many panels listen', () => {
    renderConsumers(
      <>
        <Consumer challengeId="c1" />
        <Consumer challengeId="c1" />
        <Consumer challengeId="c2" />
        <Consumer challengeId="c3" active={false} />
      </>,
    );
    expect(streams.opened.sort()).toEqual([
      '/api/challenges/c1/environment/live',
      '/api/challenges/c2/environment/live',
    ]);
  });

  it('closes the stream when the last listener leaves', () => {
    const { rerender } = renderConsumers(
      <>
        <Consumer challengeId="c1" />
        <Consumer challengeId="c1" />
      </>,
    );
    const wrap = (children) => (
      <QueryClientProvider client={createTestQueryClient()}>
        <EnvironmentLiveProvider>{children}</EnvironmentLiveProvider>
      </QueryClientProvider>
    );
    expect(streams.closed).toEqual([]);
    rerender(wrap(<Consumer challengeId="c1" active={false} />));
    expect(streams.closed).toContain('/api/challenges/c1/environment/live');
  });

  it('hands the fallback poll interval to the listeners while the stream is down', () => {
    streams.interval = 15_000;
    renderConsumers(<Consumer challengeId="c1" />);
    expect(screen.getByTestId('interval-c1')).toHaveTextContent('15000');
  });

  it('polls nothing without a provider', () => {
    render(<Consumer challengeId="c1" />);
    expect(screen.getByTestId('interval-c1')).toHaveTextContent('false');
    expect(streams.opened).toEqual([]);
  });
});
