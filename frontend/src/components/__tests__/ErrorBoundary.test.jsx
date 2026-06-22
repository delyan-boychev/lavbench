import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ErrorBoundary from '../ErrorBoundary';

function Bomb({ shouldThrow }) {
  if (shouldThrow) {
    throw new Error('Test error');
  }
  return <div>Normal render</div>;
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {
      /* noop */
    });
    vi.stubGlobal('window', {
      location: { reload: vi.fn() },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders children normally when no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">Hello</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('child')).toHaveTextContent('Hello');
  });

  it('catches error and displays fallback UI', () => {
    const originalConsoleError = console.error;
    console.error = vi.fn();
    try {
      render(
        <ErrorBoundary>
          <Bomb shouldThrow={true} />
        </ErrorBoundary>,
      );
      expect(screen.getByText('Something went wrong')).toBeTruthy();
      expect(screen.getByText('Refresh Page')).toBeTruthy();
    } finally {
      console.error = originalConsoleError;
    }
  });

  it('shows custom fallback when provided', () => {
    const originalConsoleError = console.error;
    console.error = vi.fn();
    try {
      render(
        <ErrorBoundary fallback={<div data-testid="custom">Custom Error UI</div>}>
          <Bomb shouldThrow={true} />
        </ErrorBoundary>,
      );
      expect(screen.getByTestId('custom')).toHaveTextContent('Custom Error UI');
    } finally {
      console.error = originalConsoleError;
    }
  });

  it('refresh button calls window.location.reload', () => {
    const reloadMock = vi.fn();
    const originalLocation = window.location;
    delete window.location;
    window.location = { reload: reloadMock };
    const originalConsoleError = console.error;
    console.error = vi.fn();
    try {
      render(
        <ErrorBoundary>
          <Bomb shouldThrow={true} />
        </ErrorBoundary>,
      );
      screen.getByText('Refresh Page').click();
      expect(reloadMock).toHaveBeenCalled();
    } finally {
      console.error = originalConsoleError;
      window.location = originalLocation;
    }
  });

  it('componentDidCatch logs error to console', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      render(
        <ErrorBoundary>
          <Bomb shouldThrow={true} />
        </ErrorBoundary>,
      );
      expect(errorSpy).toHaveBeenCalled();
    } finally {
      errorSpy.mockRestore();
    }
  });
});
