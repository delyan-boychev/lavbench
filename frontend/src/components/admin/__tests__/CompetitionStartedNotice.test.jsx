import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompetitionStartedNotice from '../CompetitionStartedNotice';

describe('CompetitionStartedNotice', () => {
  it('explains why a jury member cannot modify competitors', () => {
    render(<CompetitionStartedNotice />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'This competition has started. Jury members cannot modify competitors.',
    );
  });

  it('explains why a jury member cannot import competitors in bulk', () => {
    render(<CompetitionStartedNotice bulk />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'This competition has started. Jury members cannot import competitors.',
    );
  });
});
