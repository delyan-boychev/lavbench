import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SubmissionList from './SubmissionList';

describe('SubmissionList Component', () => {
  it('renders loading indicator when loading is true', () => {
    render(
      <SubmissionList
        submissions={[]}
        selected={null}
        onSelect={() => {}}
        loading={true}
      />
    );
    expect(screen.getByText('Loading submissions...')).toBeInTheDocument();
  });

  it('renders empty message when submissions list is empty or null', () => {
    const { rerender } = render(
      <SubmissionList
        submissions={null}
        selected={null}
        onSelect={() => {}}
        loading={false}
      />
    );
    expect(screen.getByText('No submissions found for this task.')).toBeInTheDocument();

    rerender(
      <SubmissionList
        submissions={[]}
        selected={null}
        onSelect={() => {}}
        loading={false}
      />
    );
    expect(screen.getByText('No submissions found for this task.')).toBeInTheDocument();
  });

  it('renders submissions list items with correct data elements', () => {
    const submissions = [
      {
        id: 101,
        status: 'completed',
        created_at: '2026-06-13T08:00:00Z',
        public_score: 0.987654,
        user: { alias_id: 'UserA' },
      },
      {
        id: 102,
        status: 'failed',
        created_at: '2026-06-13T08:15:00Z',
        public_score: null,
        user: null,
      },
    ];

    render(
      <SubmissionList
        submissions={submissions}
        selected={null}
        onSelect={() => {}}
        total={2}
        page={1}
        pages={1}
        perPage={10}
        onPageChange={() => {}}
      />
    );

    // Total label
    expect(screen.getByText('Submissions (2)')).toBeInTheDocument();

    // Submission 101 details
    expect(screen.getByText('#101')).toBeInTheDocument();
    expect(screen.getByText('✓ Completed')).toBeInTheDocument();
    expect(screen.getByText('0.9877')).toBeInTheDocument(); // formatted to 4 decimals
    expect(screen.getByText('Alias: UserA')).toBeInTheDocument();

    // Submission 102 details
    expect(screen.getByText('#102')).toBeInTheDocument();
    expect(screen.getByText('✗ Failed')).toBeInTheDocument();
    expect(screen.queryByText('Alias: UserB')).not.toBeInTheDocument();
  });

  it('triggers onSelect callback when clicking a submission row', () => {
    const submissions = [
      { id: 101, status: 'completed', created_at: '2026-06-13T08:00:00Z' },
    ];
    const handleSelect = vi.fn();

    render(
      <SubmissionList
        submissions={submissions}
        selected={null}
        onSelect={handleSelect}
        total={1}
        page={1}
        pages={1}
        perPage={10}
        onPageChange={() => {}}
      />
    );

    fireEvent.click(screen.getByText('#101'));
    expect(handleSelect).toHaveBeenCalledWith(submissions[0]);
  });
});
