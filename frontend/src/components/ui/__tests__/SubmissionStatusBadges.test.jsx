import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SubmissionStatusBadges from '../SubmissionStatusBadges';
import { isPlatformFailure } from '../../../utils/submissionStatus';

describe('SubmissionStatusBadges', () => {
  it('shows only the status for a submission whose code failed', () => {
    render(<SubmissionStatusBadges submission={{ status: 'failed', detailed_status: 'failed' }} />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.queryByText('Platform error')).not.toBeInTheDocument();
  });

  it('adds the platform error badge when the platform failed the submission', () => {
    render(
      <SubmissionStatusBadges submission={{ status: 'failed', detailed_status: 'failed_infra' }} />,
    );
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Platform error')).toBeInTheDocument();
  });

  it('shows only the status for a completed submission', () => {
    render(
      <SubmissionStatusBadges submission={{ status: 'completed', detailed_status: 'completed' }} />,
    );
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.queryByText('Platform error')).not.toBeInTheDocument();
  });

  it.each([
    [{ detailed_status: 'failed_infra' }, true],
    [{ detailed_status: 'failed' }, false],
    [{ detailed_status: null }, false],
    [null, false],
  ])('isPlatformFailure(%o) is %s', (submission, expected) => {
    expect(isPlatformFailure(submission)).toBe(expected);
  });
});
