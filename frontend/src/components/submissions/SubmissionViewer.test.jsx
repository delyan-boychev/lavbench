import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import SubmissionViewer from './SubmissionViewer';

vi.mock('../../AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    currentUser: { role: 'competitor', username: 'test_comp' }
  })
}));

describe('SubmissionViewer Component', () => {
  it('renders empty state message when no submission is selected', () => {
    render(<SubmissionViewer submission={null} currentUser={{ role: 'competitor' }} />);
    expect(screen.getByText('Select a submission to view details.')).toBeInTheDocument();
  });

  it('renders submission details and score correctly', () => {
    const mockSubmission = {
      id: 42,
      status: 'completed',
      public_score: 0.9234,
      private_score: 0.9567,
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: JSON.stringify([{ id: 1, type: 'code', source: "print('hello')" }])
    };

    render(
      <SubmissionViewer 
        submission={mockSubmission} 
        currentUser={{ role: 'competitor' }} 
      />
    );

    expect(screen.getByText('Submission #42')).toBeInTheDocument();
    expect(screen.getByText('Alias: Quantum-Falcon-402')).toBeInTheDocument();
    expect(screen.getByText('0.9234')).toBeInTheDocument();
    expect(screen.getByText('0.9567')).toBeInTheDocument();
  });

  it('renders final selection toggle and triggers callback when clicked', () => {
    const mockSubmission = {
      id: 42,
      status: 'completed',
      is_final_selection: false,
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: '[]'
    };
    const onSelectFinalMock = vi.fn();

    render(
      <SubmissionViewer 
        submission={mockSubmission} 
        currentUser={{ role: 'competitor' }} 
        onSelectFinal={onSelectFinalMock}
      />
    );

    const checkbox = screen.getByLabelText('Select as final submission (enforces anti-overfitting rules).');
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(onSelectFinalMock).toHaveBeenCalledWith(42);
  });

  it('disables the toggle and displays post-deadline warning if submission is after deadline', () => {
    const mockSubmission = {
      id: 42,
      status: 'completed',
      is_final_selection: false,
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: '[]'
    };

    render(
      <SubmissionViewer 
        submission={mockSubmission} 
        currentUser={{ role: 'competitor' }} 
        isSelectionDisabled={true}
        isSubmissionAfterDeadline={true}
      />
    );

    const checkbox = screen.getByLabelText('Select as final submission (enforces anti-overfitting rules).');
    expect(checkbox).toBeDisabled();
    expect(screen.getByText('Cannot select a submission created after the stage deadline.')).toBeInTheDocument();
  });

  it('disables the toggle and displays selection window closed warning when grace period is over', () => {
    const mockSubmission = {
      id: 42,
      status: 'completed',
      is_final_selection: false,
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: '[]'
    };

    render(
      <SubmissionViewer 
        submission={mockSubmission} 
        currentUser={{ role: 'competitor' }} 
        isSelectionDisabled={true}
        isSubmissionAfterDeadline={false}
      />
    );

    const checkbox = screen.getByLabelText('Select as final submission (enforces anti-overfitting rules).');
    expect(checkbox).toBeDisabled();
    expect(screen.getByText('The final selection window for this stage has closed.')).toBeInTheDocument();
  });

  it('instantiates EventSource and displays live logs when submission is running', () => {
    const mockSubmission = {
      id: 42,
      status: 'running',
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: '[]'
    };

    const mockEventSourceInstances = [];
    class MockEventSource {
      constructor(url) {
        this.url = url;
        mockEventSourceInstances.push(this);
      }
      close = vi.fn();
    }
    vi.stubGlobal('EventSource', MockEventSource);

    render(
      <SubmissionViewer 
        submission={mockSubmission} 
        currentUser={{ role: 'competitor' }} 
      />
    );

    expect(mockEventSourceInstances.length).toBe(1);
    expect(mockEventSourceInstances[0].url).toContain('/api/submissions/42/logs/live');
    expect(screen.getByText(/submissions.connecting_live_logs/i)).toBeInTheDocument();

    const event = { data: JSON.stringify({ log: 'Building docker sandbox...' }) };
    act(() => {
      mockEventSourceInstances[0].onmessage(event);
    });

    expect(screen.getByText(/Building docker sandbox/i)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
