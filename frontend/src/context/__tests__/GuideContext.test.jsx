import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { GuideProvider, useGuide } from '../GuideContext';
import DocsMarkdown from '../../components/layout/DocsMarkdown';

function Probe() {
  const { isOpen, tab, section, openGuide, closeGuide, selectTab } = useGuide();
  return (
    <div>
      <span data-testid="state">{`${isOpen}|${tab}|${section}`}</span>
      <button onClick={() => openGuide('admin', '10')}>learn</button>
      <button onClick={() => openGuide()}>docs</button>
      <button onClick={() => selectTab('jury')}>jury</button>
      <button onClick={closeGuide}>close</button>
    </div>
  );
}

describe('GuideContext', () => {
  it('opens on a tab and section, and forgets the section on a tab change or close', () => {
    render(
      <GuideProvider>
        <Probe />
      </GuideProvider>,
    );
    const state = () => screen.getByTestId('state').textContent;
    expect(state()).toBe('false|competitor|null');
    fireEvent.click(screen.getByText('learn'));
    expect(state()).toBe('true|admin|10');
    fireEvent.click(screen.getByText('jury'));
    expect(state()).toBe('true|jury|null');
    fireEvent.click(screen.getByText('close'));
    expect(state()).toBe('false|jury|null');
    fireEvent.click(screen.getByText('docs'));
    expect(state()).toBe('true|jury|null');
  });

  it('starts over when another user signs in', () => {
    const { rerender } = render(
      <GuideProvider userId="admin-1">
        <Probe />
      </GuideProvider>,
    );
    const state = () => screen.getByTestId('state').textContent;
    fireEvent.click(screen.getByText('learn'));
    expect(state()).toBe('true|admin|10');
    rerender(
      <GuideProvider userId={null}>
        <Probe />
      </GuideProvider>,
    );
    expect(state()).toBe('false|competitor|null');
    rerender(
      <GuideProvider userId="student-1">
        <Probe />
      </GuideProvider>,
    );
    expect(state()).toBe('false|competitor|null');
  });

  it('needs its provider', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow('useGuide must be used within GuideProvider');
  });
});

describe('DocsMarkdown', () => {
  it('scrolls to the numbered section in any language', async () => {
    const scrolled = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView() {
      scrolled.push(this.textContent);
    };
    try {
      render(
        <DocsMarkdown
          content={'## 1. Начало\n\ntext\n\n## 10. Работни пространства\n\nmore'}
          section="10"
        />,
      );
      await waitFor(() => expect(scrolled).toEqual(['10. Работни пространства']));
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });
});
