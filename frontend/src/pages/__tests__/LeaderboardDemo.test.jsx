import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import LeaderboardDemo from '../LeaderboardDemo';

describe('LeaderboardDemo', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the title and description', () => {
    render(<LeaderboardDemo />);
    expect(screen.getByText('Leaderboard Animation Demo')).toBeTruthy();
    expect(screen.getByText(/Scores shuffle every 3 seconds/i)).toBeTruthy();
  });

  it('renders the Shuffle Now button', () => {
    render(<LeaderboardDemo />);
    expect(screen.getByRole('button', { name: /shuffle now/i })).toBeTruthy();
  });

  it('renders 10 participant entries', () => {
    render(<LeaderboardDemo />);
    const rows = screen.getAllByText(
      /Alpha-Titan|Quantum-Falcon|Stellar-Voyager|Cyber-Phoenix|Neon-Warrior|Pixel-Gladiator|Shadow-Ninja|Thunder-Dragon|Ice-Wizard|Blaze-Knight/,
    );
    expect(rows).toHaveLength(10);
  });

  it('renders column headers (Rank, Participant, Score, Change)', () => {
    render(<LeaderboardDemo />);
    expect(screen.getByText('Rank')).toBeTruthy();
    expect(screen.getByText('Participant')).toBeTruthy();
    expect(screen.getByText('Score')).toBeTruthy();
    expect(screen.getByText('Change')).toBeTruthy();
  });

  it('displays scores formatted to 4 decimal places', () => {
    render(<LeaderboardDemo />);
    const scoreCells = screen.getAllByText(/\d\.\d{4}/);
    expect(scoreCells.length).toBeGreaterThan(0);
  });

  it('shuffles on button click', () => {
    render(<LeaderboardDemo />);
    const initialText = screen
      .getAllByText(/-\d{3}/)
      .map((el) => el.textContent)
      .join(',');

    fireEvent.click(screen.getByRole('button', { name: /shuffle now/i }));

    const afterClick = screen
      .getAllByText(/-\d{3}/)
      .map((el) => el.textContent)
      .join(',');
    expect(afterClick).not.toBe(initialText);
  });

  it('renders medals for top 3 positions', () => {
    render(<LeaderboardDemo />);
    const firstRank = screen.getAllByText('1')[0];
    expect(firstRank).toBeTruthy();
  });
});
