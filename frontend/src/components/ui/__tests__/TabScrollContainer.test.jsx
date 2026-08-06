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
});
