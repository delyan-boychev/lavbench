import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import SubmissionViewer from '../SubmissionViewer';

vi.stubGlobal(
  'EventSource',
  class {
    constructor() {}
    close = vi.fn();
  },
);

vi.mock('../../../AuthContext', () => ({
  useAuth: () => ({
    currentUser: { role: 'competitor', username: 'test_comp' },
  }),
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
      code_cells: JSON.stringify([{ id: 1, type: 'code', source: "print('hello')" }]),
    };

    render(<SubmissionViewer submission={mockSubmission} currentUser={{ role: 'competitor' }} />);

    expect(screen.getByText('Submission #42')).toBeInTheDocument();
    expect(screen.getByText('Alias: Quantum-Falcon-402')).toBeInTheDocument();
    expect(screen.getByText('0.9234')).toBeInTheDocument();
    expect(screen.getByText('0.9567')).toBeInTheDocument();
  });

  it('explains that an infrastructure failure does not count toward the limits', () => {
    const mockSubmission = {
      id: 43,
      status: 'failed',
      detailed_status: 'failed_infra',
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: JSON.stringify([{ id: 1, type: 'code', source: 'print(1)' }]),
    };

    render(<SubmissionViewer submission={mockSubmission} currentUser={{ role: 'competitor' }} />);

    expect(screen.getByText('Platform error')).toBeInTheDocument();
    expect(screen.getByText(/does not count toward your submission limits/)).toBeInTheDocument();
  });

  it('renders final selection toggle and triggers callback when clicked', () => {
    const mockSubmission = {
      id: 42,
      status: 'completed',
      is_final_selection: false,
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: '[]',
    };
    const onSelectFinalMock = vi.fn();

    render(
      <SubmissionViewer
        submission={mockSubmission}
        currentUser={{ role: 'competitor' }}
        onSelectFinal={onSelectFinalMock}
      />,
    );

    const checkbox = screen.getByLabelText(
      'Select as final submission (enforces anti-overfitting rules).',
    );
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
      code_cells: '[]',
    };

    render(
      <SubmissionViewer
        submission={mockSubmission}
        currentUser={{ role: 'competitor' }}
        isSelectionDisabled={true}
        isSubmissionAfterDeadline={true}
      />,
    );

    const checkbox = screen.getByLabelText(
      'Select as final submission (enforces anti-overfitting rules).',
    );
    expect(checkbox).toBeDisabled();
    expect(
      screen.getByText('Cannot select a submission created after the stage deadline.'),
    ).toBeInTheDocument();
  });

  it('disables the toggle and displays selection window closed warning when grace period is over', () => {
    const mockSubmission = {
      id: 42,
      status: 'completed',
      is_final_selection: false,
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: '[]',
    };

    render(
      <SubmissionViewer
        submission={mockSubmission}
        currentUser={{ role: 'competitor' }}
        isSelectionDisabled={true}
        isSubmissionAfterDeadline={false}
      />,
    );

    const checkbox = screen.getByLabelText(
      'Select as final submission (enforces anti-overfitting rules).',
    );
    expect(checkbox).toBeDisabled();
    expect(
      screen.getByText('The final selection window for this stage has closed.'),
    ).toBeInTheDocument();
  });

  it('instantiates EventSource and displays live logs when submission is running', () => {
    const mockSubmission = {
      id: 42,
      status: 'running',
      user: { alias_id: 'Quantum-Falcon-402' },
      code_cells: '[]',
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

    render(<SubmissionViewer submission={mockSubmission} currentUser={{ role: 'competitor' }} />);

    expect(mockEventSourceInstances.length).toBe(1);
    expect(mockEventSourceInstances[0].url).toContain('/api/submissions/42/logs/live');

    const event = { data: JSON.stringify({ log: 'Building docker sandbox...' }) };
    act(() => {
      mockEventSourceInstances[0].onmessage(event);
    });

    expect(screen.getByText(/Building docker sandbox/i)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it('batches bursts of live log lines into a single delayed flush', () => {
    vi.useFakeTimers();
    const instances = [];
    vi.stubGlobal(
      'EventSource',
      class {
        constructor() {
          instances.push(this);
        }
        close = vi.fn();
      },
    );
    const submission = { id: 7, status: 'running', code_cells: '[]' };
    render(<SubmissionViewer submission={submission} currentUser={{ role: 'competitor' }} />);
    const es = instances[instances.length - 1];
    const send = (log) => act(() => es.onmessage({ data: JSON.stringify({ log }) }));

    send('first line');
    expect(screen.getByText(/first line/)).toBeInTheDocument();

    send('second line');
    send('third line');
    expect(screen.queryByText(/second line/)).toBeNull();

    act(() => vi.advanceTimersByTime(250));
    expect(screen.getByText(/third line/)).toBeInTheDocument();
    expect(screen.getByText(/second line/)).toBeInTheDocument();

    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  describe('log stream', () => {
    let instances;

    function stubStreams() {
      instances = [];
      vi.stubGlobal(
        'EventSource',
        class {
          constructor(url) {
            this.url = url;
            this.close = vi.fn();
            instances.push(this);
          }
        },
      );
    }

    const send = (es, payload) => act(() => es.onmessage({ data: JSON.stringify(payload) }));

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it('shows the stored log of a finished submission without opening a stream', () => {
      stubStreams();
      const submission = { id: 5, status: 'failed', logs: 'Traceback: boom', code_cells: '[]' };
      render(<SubmissionViewer submission={submission} currentUser={{ role: 'competitor' }} />);
      expect(instances).toHaveLength(0);
      expect(screen.getByText('Traceback: boom')).toBeInTheDocument();
    });

    it('opens the stream only once a queued submission starts running', () => {
      stubStreams();
      const queued = { id: 9, status: 'queued', code_cells: '[]' };
      const { rerender } = render(
        <SubmissionViewer submission={queued} currentUser={{ role: 'competitor' }} />,
      );
      expect(instances).toHaveLength(0);

      rerender(
        <SubmissionViewer
          submission={{ ...queued, status: 'running' }}
          currentUser={{ role: 'competitor' }}
        />,
      );
      expect(instances).toHaveLength(1);
      expect(instances[0].url).toBe('/api/submissions/9/logs/live');
    });

    it('starts the live log over on every (re)connect because the server replays it', () => {
      stubStreams();
      const submission = { id: 3, status: 'running', code_cells: '[]' };
      render(<SubmissionViewer submission={submission} currentUser={{ role: 'competitor' }} />);
      const es = instances[0];
      send(es, { info: 'connected' });
      send(es, { log: 'replayed line' });
      expect(screen.getByText(/replayed line/)).toBeInTheDocument();

      send(es, { info: 'connected' });
      expect(screen.queryByText(/replayed line/)).toBeNull();
    });

    it('reports a final status to the parent and closes the stream', () => {
      stubStreams();
      const onSubmissionUpdate = vi.fn();
      const submission = { id: 11, status: 'running', code_cells: '[]' };
      render(
        <SubmissionViewer
          submission={submission}
          currentUser={{ role: 'competitor' }}
          onSubmissionUpdate={onSubmissionUpdate}
        />,
      );
      const es = instances[0];
      send(es, { status: 'running' });
      expect(onSubmissionUpdate).not.toHaveBeenCalled();

      send(es, { status: 'completed' });
      expect(onSubmissionUpdate).toHaveBeenCalledWith(11);
      expect(es.close).toHaveBeenCalled();
    });

    it('closes the stream when the parent data shows the submission finished', () => {
      stubStreams();
      const running = { id: 12, status: 'running', code_cells: '[]' };
      const { rerender } = render(
        <SubmissionViewer submission={running} currentUser={{ role: 'competitor' }} />,
      );
      const es = instances[0];
      rerender(
        <SubmissionViewer
          submission={{ ...running, status: 'completed', logs: 'stored log' }}
          currentUser={{ role: 'competitor' }}
        />,
      );
      expect(es.close).toHaveBeenCalled();
      expect(instances).toHaveLength(1);
      expect(screen.getByText('stored log')).toBeInTheDocument();
    });
  });
});
