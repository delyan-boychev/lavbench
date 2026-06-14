import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChallengeConfig from './ChallengeConfig';

describe('ChallengeConfig Component', () => {
  const mockTimezones = [
    { value: 'UTC', label: 'UTC' },
    { value: 'Europe/Sofia', label: 'Europe/Sofia' }
  ];

  const mockNewChallenge = {
    title: 'Test Competition',
    description: 'Test Description',
    max_eval_requests: 10,
    ram_limit_mb: 8192,
    time_limit_sec: 300,
    gpu_required: true,
    start_time: '2026-06-14T12:00',
    end_time: '2026-06-15T12:00',
    timezone: 'UTC',
    double_blind: true,
    is_frozen: false
  };

  it('renders input fields with initial values', () => {
    const handleCreateChallenge = vi.fn();
    const setNewChallenge = vi.fn();

    render(
      <ChallengeConfig
        handleCreateChallenge={handleCreateChallenge}
        newChallenge={mockNewChallenge}
        setNewChallenge={setNewChallenge}
        timezones={mockTimezones}
      />
    );

    expect(screen.getByLabelText(/Competition Title/i)).toHaveValue('Test Competition');
    expect(screen.getByLabelText(/Daily Limits \(Submissions\/day\)/i)).toHaveValue(10);
    expect(screen.getByLabelText(/RAM Limit override \(MB\)/i)).toHaveValue(8192);
    expect(screen.getByLabelText(/Time limit override \(sec\)/i)).toHaveValue(300);
    expect(screen.getByLabelText(/Start Time/i)).toHaveValue('2026-06-14T12:00');
    expect(screen.getByLabelText(/End Time/i)).toHaveValue('2026-06-15T12:00');
  });

  it('triggers setNewChallenge on input changes', () => {
    const handleCreateChallenge = vi.fn();
    const setNewChallenge = vi.fn();

    render(
      <ChallengeConfig
        handleCreateChallenge={handleCreateChallenge}
        newChallenge={mockNewChallenge}
        setNewChallenge={setNewChallenge}
        timezones={mockTimezones}
      />
    );

    const titleInput = screen.getByLabelText(/Competition Title/i);
    fireEvent.change(titleInput, { target: { value: 'New Title' } });

    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'New Title' })
    );
  });

  it('submits form and triggers handleCreateChallenge', () => {
    const handleCreateChallenge = vi.fn((e) => e.preventDefault());
    const setNewChallenge = vi.fn();

    render(
      <ChallengeConfig
        handleCreateChallenge={handleCreateChallenge}
        newChallenge={mockNewChallenge}
        setNewChallenge={setNewChallenge}
        timezones={mockTimezones}
      />
    );

    const submitBtn = screen.getByRole('button', { name: /Create Competition/i });
    fireEvent.click(submitBtn);

    expect(handleCreateChallenge).toHaveBeenCalledTimes(1);
  });
});
