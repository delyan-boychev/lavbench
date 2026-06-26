import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import CountdownTimer from '../CountdownTimer';

const NOW = new Date('2026-06-13T12:00:00Z').getTime();

function makeStage(overrides = {}) {
  return {
    id: 1,
    stage_number: 1,
    title: 'Stage 1',
    start_time: '2026-06-13T10:00:00Z',
    end_time: '2026-06-13T14:00:00Z',
    is_finalized: false,
    ...overrides,
  };
}

function makeChallenge(overrides = {}) {
  return {
    id: 1,
    title: 'Challenge Alpha',
    start_time: '2026-06-13T10:00:00Z',
    end_time: '2026-06-13T18:00:00Z',
    deadline_grace_period_seconds: 60,
    stages: [makeStage()],
    scores_finalized: false,
    ...overrides,
  };
}

describe('CountdownTimer Component', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders null when no challenge is provided', () => {
    const { container } = render(<CountdownTimer selectedChallenge={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders null when challenge has no stages and no start/end time', () => {
    const { container } = render(<CountdownTimer selectedChallenge={{ id: 1, title: 'Empty' }} />);
    expect(container.firstChild).toBeNull();
  });

  describe('time remaining (active stage)', () => {
    it('renders green when more than 30 min left', () => {
      // NOW is 12:00, stage ends at 14:00 → 120 min left
      render(<CountdownTimer selectedChallenge={makeChallenge()} />);
      expect(screen.getByText(/Stage 1 left:/)).toBeInTheDocument();
      expect(screen.getByText(/02:00:00/)).toBeInTheDocument();
      const el = screen.getByTitle('Time remaining in Stage 1');
      expect(el).toBeInTheDocument();
      expect(el.style.color).toBe('#10b981');
      expect(el.className).not.toContain('animate-flash-red');
    });

    it('renders yellow when 15-30 min left', () => {
      const stage = makeStage({ end_time: '2026-06-13T12:20:00Z' });
      render(<CountdownTimer selectedChallenge={makeChallenge({ stages: [stage] })} />);
      const el = screen.getByTitle('Time remaining in Stage 1');
      expect(el.style.color).toBe('#f59e0b');
    });

    it('renders red (no flash) when 5-15 min left', () => {
      const stage = makeStage({ end_time: '2026-06-13T12:10:00Z' });
      render(<CountdownTimer selectedChallenge={makeChallenge({ stages: [stage] })} />);
      const el = screen.getByTitle('Time remaining in Stage 1');
      expect(el.style.color).toBe('#ef4444');
      expect(el.className).not.toContain('animate-flash-red');
    });

    it('renders red flashing when less than 5 min left', () => {
      const stage = makeStage({ end_time: '2026-06-13T12:03:00Z' });
      render(<CountdownTimer selectedChallenge={makeChallenge({ stages: [stage] })} />);
      const el = screen.getByTitle('Time remaining in Stage 1');
      expect(el.style.color).toBe('#ef4444');
      expect(el.className).toContain('animate-flash-red');
    });
  });

  describe('grace period', () => {
    it('renders amber flashing with seconds display during grace period', () => {
      // Stage ended at 11:59, we're at 12:00 (1 min into 60s grace period)
      const stage = makeStage({ end_time: '2026-06-13T11:59:00Z' });
      render(<CountdownTimer selectedChallenge={makeChallenge({ stages: [stage] })} />);
      const el = screen.getByTitle('Grace period active');
      expect(el).toBeInTheDocument();
      expect(el.style.color).toBe('#f97316');
      expect(el.className).toContain('animate-flash-red');
      // 60s grace - 60s elapsed = 0s remaining (ceil(0) = 0)
      expect(screen.getByText(/Grace Period:/)).toBeInTheDocument();
    });

    it('shows correct remaining grace seconds', () => {
      // Stage ended at 11:59:30, we're at 12:00:00 → 30s into 60s grace → 30s remaining
      const stage = makeStage({ end_time: '2026-06-13T11:59:30Z' });
      render(<CountdownTimer selectedChallenge={makeChallenge({ stages: [stage] })} />);
      expect(screen.getByText(/30s/)).toBeInTheDocument();
    });
  });

  describe('challenge-level time remaining', () => {
    it('shows time left when no active stage but challenge has end_time', () => {
      // No stages, challenge ends at 18:00 → 360 min left
      const challenge = makeChallenge({ stages: [] });
      render(<CountdownTimer selectedChallenge={challenge} />);
      expect(screen.getByText(/Time left:/)).toBeInTheDocument();
      expect(screen.getByText(/06:00:00/)).toBeInTheDocument();
      expect(screen.getByTitle('Time remaining')).toBeInTheDocument();
    });

    it('does not show time left when scores are finalized', () => {
      const challenge = makeChallenge({ stages: [], scores_finalized: true });
      const { container } = render(<CountdownTimer selectedChallenge={challenge} />);
      expect(container.firstChild).toBeNull();
    });
  });

  describe('stage starting soon', () => {
    it('renders purple when an upcoming stage exists', () => {
      // No active stage (past), one upcoming
      const pastStage = makeStage({
        id: 1,
        stage_number: 1,
        end_time: '2026-06-13T11:00:00Z',
        is_finalized: true,
      });
      const upcomingStage = makeStage({
        id: 2,
        stage_number: 2,
        start_time: '2026-06-13T13:00:00Z',
        end_time: '2026-06-13T17:00:00Z',
      });
      render(
        <CountdownTimer
          selectedChallenge={makeChallenge({ stages: [pastStage, upcomingStage], end_time: null })}
        />,
      );
      expect(screen.getByText(/Stage 2 starts in:/)).toBeInTheDocument();
      expect(screen.getByText(/01:00:00/)).toBeInTheDocument();
      const el = screen.getByTitle('Time until Stage 2 starts');
      expect(el.style.color).toBe('#a855f7');
    });

    it('flashes purple when less than 5 min to stage start', () => {
      const pastStage = makeStage({
        id: 1,
        stage_number: 1,
        end_time: '2026-06-13T11:00:00Z',
        is_finalized: true,
      });
      const upcomingStage = makeStage({
        id: 2,
        stage_number: 2,
        start_time: '2026-06-13T12:02:00Z',
        end_time: '2026-06-13T17:00:00Z',
      });
      render(
        <CountdownTimer
          selectedChallenge={makeChallenge({ stages: [pastStage, upcomingStage], end_time: null })}
        />,
      );
      const el = screen.getByTitle('Time until Stage 2 starts');
      expect(el.style.color).toBe('#c084fc');
      expect(el.className).toContain('animate-flash-purple');
    });
  });

  describe('challenge starting soon', () => {
    it('renders purple with starts-in message when challenge starts in future', () => {
      const challenge = makeChallenge({
        stages: [],
        start_time: '2026-06-13T14:00:00Z',
        end_time: '2026-06-13T18:00:00Z',
      });
      render(<CountdownTimer selectedChallenge={challenge} />);
      expect(screen.getByText(/Starts in:/)).toBeInTheDocument();
      expect(screen.getByText(/02:00:00/)).toBeInTheDocument();
      const el = screen.getByTitle('Time until start');
      expect(el.style.color).toBe('#a855f7');
    });

    it('flashes purple when less than 5 min to start', () => {
      const challenge = makeChallenge({
        stages: [],
        start_time: '2026-06-13T12:02:00Z',
        end_time: '2026-06-13T18:00:00Z',
      });
      render(<CountdownTimer selectedChallenge={challenge} />);
      const el = screen.getByTitle('Time until start');
      expect(el.style.color).toBe('#c084fc');
      expect(el.className).toContain('animate-flash-purple');
    });

    it('renders null when challenge is archived', () => {
      const challenge = makeChallenge({
        stages: [],
        start_time: '2026-06-13T14:00:00Z',
        is_archived: true,
      });
      const { container } = render(<CountdownTimer selectedChallenge={challenge} />);
      expect(container.firstChild).toBeNull();
    });

    it('renders null when scores are finalized', () => {
      const challenge = makeChallenge({
        stages: [],
        start_time: '2026-06-13T14:00:00Z',
        scores_finalized: true,
      });
      const { container } = render(<CountdownTimer selectedChallenge={challenge} />);
      expect(container.firstChild).toBeNull();
    });
  });

  describe('timer interval lifecycle', () => {
    it('updates display after advancing time', async () => {
      const stage = makeStage({ end_time: '2026-06-13T12:01:00Z' }); // 1 min from now
      render(<CountdownTimer selectedChallenge={makeChallenge({ stages: [stage] })} />);
      expect(screen.getByText(/00:01:00/)).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(15000);
      });
      expect(screen.getByText(/00:00:45/)).toBeInTheDocument();
    });
  });

  describe('no upcoming stage and no challenge start', () => {
    it('renders null when no stages match and challenge has already started', () => {
      const challenge = makeChallenge({
        stages: [],
        start_time: '2026-06-13T09:00:00Z',
        end_time: '2026-06-13T10:00:00Z',
      });
      const { container } = render(<CountdownTimer selectedChallenge={challenge} />);
      expect(container.firstChild).toBeNull();
    });
  });
});
