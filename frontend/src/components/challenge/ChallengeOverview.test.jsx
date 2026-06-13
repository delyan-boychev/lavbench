import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ChallengeOverview from './ChallengeOverview';

describe('ChallengeOverview Component', () => {
  it('renders nothing when challenge is not provided', () => {
    const { container } = render(<ChallengeOverview challenge={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders challenge title, description, and active status badge', () => {
    const challenge = {
      title: 'Image Classification Benchmark',
      description: 'Classify images in a restricted RAM environment.',
      is_archived: false,
      max_eval_requests: 5,
      ram_limit_mb: 4096,
      time_limit_sec: 60,
      gpu_required: false,
      tasks: [1, 2],
    };

    render(<ChallengeOverview challenge={challenge} />);

    expect(screen.getByText('Image Classification Benchmark')).toBeInTheDocument();
    expect(screen.getByText('Classify images in a restricted RAM environment.')).toBeInTheDocument();
    expect(screen.getByText('● Active')).toBeInTheDocument();

    // Verify stats cards are rendered
    expect(screen.getByText('Daily Limit')).toBeInTheDocument();
    expect(screen.getByText('5 submissions')).toBeInTheDocument();

    expect(screen.getByText('RAM Limit')).toBeInTheDocument();
    expect(screen.getByText('4 GB')).toBeInTheDocument(); // 4096 / 1024 = 4

    expect(screen.getByText('Time Limit')).toBeInTheDocument();
    expect(screen.getByText('60s')).toBeInTheDocument();

    expect(screen.getByText('Hardware')).toBeInTheDocument();
    expect(screen.getByText('CPU Only')).toBeInTheDocument();

    expect(screen.getByText('Tasks')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders archived status badge and GPU cluster hardware indicator', () => {
    const challenge = {
      title: 'GPU Task',
      description: 'Heavy models.',
      is_archived: true,
      max_eval_requests: 10,
      ram_limit_mb: 8192,
      time_limit_sec: 300,
      gpu_required: true,
    };

    render(<ChallengeOverview challenge={challenge} />);

    expect(screen.getByText('■ Archived')).toBeInTheDocument();
    expect(screen.getByText('8 GB')).toBeInTheDocument();
    expect(screen.getByText('GPU Cluster')).toBeInTheDocument();
  });

  it('renders start/end dates and stage dates in the correct timezone', () => {
    const challenge = {
      title: 'Timezone Challenge',
      description: 'Check dates and times.',
      is_archived: false,
      max_eval_requests: 5,
      ram_limit_mb: 2048,
      time_limit_sec: 30,
      gpu_required: false,
      start_time: '2026-06-13T18:00:00Z',
      end_time: '2026-06-14T18:00:00Z',
      timezone: 'Europe/Sofia',
      stages: [
        {
          id: 1,
          stage_number: 1,
          title: 'Stage One',
          start_time: '2026-06-13T18:00:00Z',
          end_time: '2026-06-13T20:00:00Z',
          is_finalized: false,
        }
      ]
    };

    render(<ChallengeOverview challenge={challenge} />);

    // In Europe/Sofia (UTC+3 in June), 18:00 UTC is 21:00 Sofia time
    expect(screen.getAllByText(/2026-06-13 21:00 \(Europe\/Sofia\)/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/2026-06-14 21:00 \(Europe\/Sofia\)/)).toBeInTheDocument();
    expect(screen.getByText(/to 2026-06-13 23:00 \(Europe\/Sofia\)/)).toBeInTheDocument();
  });
});
