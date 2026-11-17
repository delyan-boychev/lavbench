import React from 'react';
import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TabScrollContainer from '../TabScrollContainer';

describe('TabScrollContainer', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}

        disconnect() {}
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('scopes its WebKit scrollbar rule to the tab container', () => {
    const { container } = render(
      <TabScrollContainer>
        <button type="button">Tab</button>
      </TabScrollContainer>,
    );
    const style = container.querySelector('style');

    expect(style).toHaveTextContent('.tab-scroll-container::-webkit-scrollbar');
    expect(style).not.toHaveTextContent('div::-webkit-scrollbar');
  });

  it('scrolls an active tab that is out of view into the strip', () => {
    const scrollTo = vi.fn();
    const { container, rerender } = render(
      <TabScrollContainer>
        <button aria-pressed="false">General</button>
      </TabScrollContainer>,
    );
    const strip = container.querySelector('.tab-scroll-container');
    strip.scrollTo = scrollTo;
    Object.defineProperty(strip, 'clientWidth', { value: 200, configurable: true });
    rerender(
      <TabScrollContainer>
        <button aria-pressed="false">General</button>
        <button aria-pressed="true">Files</button>
      </TabScrollContainer>,
    );
    const files = strip.querySelectorAll('button')[1];
    Object.defineProperty(files, 'offsetLeft', { value: 500, configurable: true });
    Object.defineProperty(files, 'offsetWidth', { value: 80, configurable: true });
    rerender(
      <TabScrollContainer>
        <button aria-pressed="false">General</button>
        <button aria-pressed="true">Files</button>
      </TabScrollContainer>,
    );
    expect(scrollTo).toHaveBeenCalledWith({ left: 476 });
  });
});
