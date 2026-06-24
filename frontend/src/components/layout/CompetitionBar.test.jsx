import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import CompetitionBar from './CompetitionBar';

// Mock AuthContext
vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock AppContext
vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

// Mock SelectField to make assertion on its presence simpler
vi.mock('../ui/SelectField', () => ({
  default: ({ options, value, onChange, placeholder }) => (
    <div data-testid="mock-custom-select">
      <span data-testid="select-placeholder">{placeholder}</span>
      <select data-testid="select-element" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
}));

describe('CompetitionBar Component', () => {
  const mockSetSelectedChallengeById = vi.fn();

  const mockChallenges = [
    { id: 1, title: 'Challenge Alpha', is_archived: false },
    { id: 2, title: 'Challenge Beta', is_archived: false },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders dropdown for jury/admin users', () => {
    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'jury_user', role: 'jury' },
    });

    useApp.mockReturnValue({
      challenges: mockChallenges,
      selectedChallenge: mockChallenges[0],
      setSelectedChallengeById: mockSetSelectedChallengeById,
    });

    render(
      <BrowserRouter>
        <CompetitionBar />
      </BrowserRouter>,
    );

    expect(screen.getByTestId('mock-custom-select')).toBeInTheDocument();
    expect(screen.queryByTestId('student-competition-label')).not.toBeInTheDocument();
    expect(screen.getByText('Challenge Alpha')).toBeInTheDocument();
  });

  it('renders stylized badge instead of selectbox for competitor (student) role', () => {
    useAuth.mockReturnValue({
      currentUser: { id: 2, username: 'student_user', role: 'competitor' },
    });

    useApp.mockReturnValue({
      challenges: mockChallenges,
      selectedChallenge: mockChallenges[0],
      setSelectedChallengeById: mockSetSelectedChallengeById,
    });

    render(
      <BrowserRouter>
        <CompetitionBar />
      </BrowserRouter>,
    );

    expect(screen.queryByTestId('mock-custom-select')).not.toBeInTheDocument();

    const badge = screen.getByTestId('student-competition-label');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Challenge Alpha');
    expect(screen.getByTitle('Your assigned competition')).toBeInTheDocument();
  });

  it('displays fallback text when student has no challenge selected', () => {
    useAuth.mockReturnValue({
      currentUser: { id: 2, username: 'student_user', role: 'competitor' },
    });

    useApp.mockReturnValue({
      challenges: mockChallenges,
      selectedChallenge: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
    });

    render(
      <BrowserRouter>
        <CompetitionBar />
      </BrowserRouter>,
    );

    const badge = screen.getByTestId('student-competition-label');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('No Competition Assigned');
  });
});
