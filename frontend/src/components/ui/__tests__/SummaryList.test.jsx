import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SummaryList from '../SummaryList';

describe('SummaryList', () => {
  it('renders each fact as a term and its value', () => {
    render(
      <SummaryList
        items={[
          { label: 'Image', value: 'Python ML' },
          { key: 'places', label: 'Places', value: <strong>42</strong> },
        ]}
      />,
    );
    const terms = screen.getAllByRole('term');
    const values = screen.getAllByRole('definition');
    expect(terms.map((term) => term.textContent)).toEqual(['Image', 'Places']);
    expect(values[0]).toHaveTextContent('Python ML');
    expect(values[1].querySelector('strong')).toHaveTextContent('42');
  });

  it('takes its own grid classes', () => {
    const { container } = render(
      <SummaryList className="grid gap-2" items={[{ label: 'Open', value: 'now' }]} />,
    );
    expect(container.querySelector('dl')).toHaveClass('grid', 'gap-2');
  });
});
