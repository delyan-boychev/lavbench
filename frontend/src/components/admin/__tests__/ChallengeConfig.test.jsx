import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: vi.fn(), confirm: vi.fn() }),
}));

vi.mock('../../ui/InputField', () => ({
  default: ({ label, value, onChange, type, multiline, rows, required }) => (
    <div>
      {label && <label>{label}</label>}
      {multiline ? (
        <textarea
          data-testid="textarea"
          value={value}
          onChange={onChange}
          rows={rows}
          required={required}
        />
      ) : (
        <input type={type || 'text'} value={value} onChange={onChange} required={required} />
      )}
    </div>
  ),
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, type, variant, className, disabled, isLoading }) => (
    <button
      type={type}
      data-variant={variant}
      className={className}
      disabled={disabled}
      aria-busy={isLoading || undefined}
    >
      {children}
    </button>
  ),
}));

vi.mock('../../ui/SelectField', () => ({
  default: ({ label, value, onChange, options, required }) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} required={required}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  ),
}));

vi.mock('../../ui/ToggleField', () => ({
  default: ({ label, id, checked, onChange }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <input type="checkbox" id={id} checked={checked} onChange={onChange} />
    </div>
  ),
}));

const catalogState = { isError: false, error: null, data: {} };
const resetCatalog = () => Object.assign(catalogState, { isError: false, error: null, data: {} });
vi.mock('../../../hooks/useEnvironmentQuery', async (importOriginal) => ({
  ...(await importOriginal()),
  useWorkspaceCatalogQuery: () => catalogState,
}));

vi.mock('../WorkspaceSettingsSection', () => ({
  default: ({ draft, onChange, errors }) => (
    <div data-testid="workspace-settings" data-errors={JSON.stringify(errors)}>
      <button type="button" onClick={() => onChange({ ...draft, enabled: true, workspace_gib: 5 })}>
        turn workspaces on
      </button>
    </div>
  ),
}));

import ChallengeConfig from '../ChallengeConfig';

const defaultProps = {
  handleCreateChallenge: vi.fn((e) => e.preventDefault()),
  newChallenge: {
    title: '',
    description: '',
    max_eval_requests: 10,
    ram_limit_mb: 8192,
    time_limit_sec: 300,
    gpu_required: true,
    start_time: '',
    end_time: '',
    is_frozen: false,
    double_blind: true,
    timezone: 'UTC',
  },
  setNewChallenge: vi.fn(),
};

describe('ChallengeConfig', () => {
  beforeEach(() => {
    resetCatalog();
  });

  it('renders the form title', () => {
    render(<ChallengeConfig {...defaultProps} />);
    expect(screen.getByText('Create New Competition Challenge')).toBeInTheDocument();
  });

  it('renders three toggle labels', () => {
    render(<ChallengeConfig {...defaultProps} />);
    expect(screen.getByText('Requires GPU Workers')).toBeInTheDocument();
    expect(screen.getByText('Double-Blind Evaluation')).toBeInTheDocument();
    expect(screen.getByText('Freeze Leaderboard & Submissions')).toBeInTheDocument();
  });

  it('renders the timezone select field', () => {
    render(<ChallengeConfig {...defaultProps} />);
    expect(screen.getByText('Competition Timezone')).toBeInTheDocument();
  });

  it('calls handleCreateChallenge on form submit', () => {
    const handleCreateChallenge = vi.fn((e) => e.preventDefault());
    render(<ChallengeConfig {...defaultProps} handleCreateChallenge={handleCreateChallenge} />);
    fireEvent.submit(screen.getByRole('button', { name: /create/i }));
    expect(handleCreateChallenge).toHaveBeenCalled();
  });

  it('gpu toggle is checked when gpu_required is true', () => {
    render(<ChallengeConfig {...defaultProps} />);
    const gpuCheckbox = screen.getByLabelText('Requires GPU Workers');
    expect(gpuCheckbox.checked).toBe(true);
  });

  it('gpu toggle is unchecked when gpu_required is false', () => {
    render(
      <ChallengeConfig
        {...defaultProps}
        newChallenge={{ ...defaultProps.newChallenge, gpu_required: false }}
      />,
    );
    const gpuCheckbox = screen.getByLabelText('Requires GPU Workers');
    expect(gpuCheckbox.checked).toBe(false);
  });

  it('double blind toggle reflects double_blind prop', () => {
    render(<ChallengeConfig {...defaultProps} />);
    const dbToggle = screen.getByLabelText('Double-Blind Evaluation');
    expect(dbToggle.checked).toBe(true);
  });

  it('frozen toggle reflects is_frozen prop', () => {
    render(<ChallengeConfig {...defaultProps} />);
    const frozenToggle = screen.getByLabelText('Freeze Leaderboard & Submissions');
    expect(frozenToggle.checked).toBe(false);
  });

  it('submit button is rendered', () => {
    render(<ChallengeConfig {...defaultProps} />);
    expect(screen.getByRole('button', { name: 'Create Competition' })).toHaveAttribute(
      'type',
      'submit',
    );
  });

  it('has no Back or Cancel, since the create form is a page of its own', () => {
    render(<ChallengeConfig {...defaultProps} />);
    expect(screen.queryByRole('button', { name: /Back/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('marks the submit button busy while creating', () => {
    render(<ChallengeConfig {...defaultProps} isCreatingChallenge />);
    const submit = screen.getByRole('button', { name: 'Create Competition' });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute('aria-busy', 'true');
  });

  it('renders input fields with initial values', () => {
    const filledChallenge = {
      ...defaultProps.newChallenge,
      title: 'Test Competition',
      description: 'Test Description',
      max_eval_requests: 10,
      ram_limit_mb: 8192,
      time_limit_sec: 300,
      start_time: '2026-06-14T12:00',
      end_time: '2026-06-15T12:00',
    };
    render(<ChallengeConfig {...defaultProps} newChallenge={filledChallenge} />);
    expect(screen.getByDisplayValue('Test Competition')).toBeInTheDocument();
    expect(screen.getByDisplayValue('10')).toBeInTheDocument();
    expect(screen.getByDisplayValue('8192')).toBeInTheDocument();
    expect(screen.getByDisplayValue('300')).toBeInTheDocument();
    expect(screen.getByDisplayValue('2026-06-14T12:00')).toBeInTheDocument();
    expect(screen.getByDisplayValue('2026-06-15T12:00')).toBeInTheDocument();
  });

  it('triggers setNewChallenge on input changes', () => {
    const setNewChallenge = vi.fn();
    const filledChallenge = {
      ...defaultProps.newChallenge,
      title: 'Test Competition',
    };
    render(
      <ChallengeConfig
        {...defaultProps}
        newChallenge={filledChallenge}
        setNewChallenge={setNewChallenge}
      />,
    );
    const titleInput = screen.getByDisplayValue('Test Competition');
    fireEvent.change(titleInput, { target: { value: 'New Title' } });
    expect(setNewChallenge).toHaveBeenCalledWith(expect.objectContaining({ title: 'New Title' }));
  });

  it('triggers setNewChallenge on all field changes', () => {
    const setNewChallenge = vi.fn();
    const filled = {
      title: 'Comp',
      description: 'Desc',
      max_eval_requests: 5,
      ram_limit_mb: 4096,
      time_limit_sec: 600,
      start_time: '2026-07-01T08:00',
      end_time: '2026-07-02T18:00',
      gpu_required: true,
      is_frozen: false,
      double_blind: true,
      timezone: 'Europe/Sofia',
      test_stage_start_time: '',
      test_stage_end_time: '',
    };
    render(
      <ChallengeConfig {...defaultProps} newChallenge={filled} setNewChallenge={setNewChallenge} />,
    );

    fireEvent.change(screen.getByDisplayValue('Desc'), { target: { value: 'New Desc' } });
    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'New Desc' }),
    );

    fireEvent.change(screen.getByDisplayValue('5'), { target: { value: '10' } });
    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ max_eval_requests: 10 }),
    );

    fireEvent.change(screen.getByDisplayValue('4096'), { target: { value: '8192' } });
    expect(setNewChallenge).toHaveBeenCalledWith(expect.objectContaining({ ram_limit_mb: 8192 }));

    fireEvent.change(screen.getByDisplayValue('600'), { target: { value: '300' } });
    expect(setNewChallenge).toHaveBeenCalledWith(expect.objectContaining({ time_limit_sec: 300 }));

    fireEvent.change(screen.getByDisplayValue('2026-07-01T08:00'), {
      target: { value: '2026-08-01T08:00' },
    });
    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ start_time: '2026-08-01T08:00' }),
    );

    fireEvent.change(screen.getByDisplayValue('2026-07-02T18:00'), {
      target: { value: '2026-08-02T18:00' },
    });
    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ end_time: '2026-08-02T18:00' }),
    );

    // The timezone options come from utils/timezones
    const select = screen.getByDisplayValue('Europe/Sofia');
    fireEvent.change(select, { target: { value: 'Europe/London' } });
    expect(setNewChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ timezone: 'Europe/London' }),
    );
  });

  it('triggers setNewChallenge on toggle changes', () => {
    const setNewChallenge = vi.fn();
    render(<ChallengeConfig {...defaultProps} setNewChallenge={setNewChallenge} />);

    fireEvent.click(screen.getByLabelText('Requires GPU Workers'));
    expect(setNewChallenge).toHaveBeenCalledWith(expect.objectContaining({ gpu_required: false }));

    fireEvent.click(screen.getByLabelText('Double-Blind Evaluation'));
    expect(setNewChallenge).toHaveBeenCalledWith(expect.objectContaining({ double_blind: false }));

    fireEvent.click(screen.getByLabelText('Freeze Leaderboard & Submissions'));
    expect(setNewChallenge).toHaveBeenCalledWith(expect.objectContaining({ is_frozen: true }));
  });

  describe('student workspaces', () => {
    it('sends the workspace section with the form', async () => {
      const handleCreateChallenge = vi.fn(async (e) => {
        e.preventDefault();
        return null;
      });
      render(<ChallengeConfig {...defaultProps} handleCreateChallenge={handleCreateChallenge} />);
      fireEvent.click(screen.getByRole('button', { name: 'turn workspaces on' }));
      fireEvent.submit(screen.getByRole('button', { name: /create/i }));
      await waitFor(() => expect(handleCreateChallenge).toHaveBeenCalled());
      expect(handleCreateChallenge.mock.calls[0][1]).toEqual({
        enabled: true,
        image_id: '',
        profile_id: '',
        workspace_gib: 5,
        auto_publish: false,
        archive_until: null,
      });
    });

    it('leaves the section out when the platform has no workspaces', async () => {
      catalogState.data = { available: false, images: [], profiles: [] };
      const handleCreateChallenge = vi.fn(async (e) => e.preventDefault());
      render(<ChallengeConfig {...defaultProps} handleCreateChallenge={handleCreateChallenge} />);
      fireEvent.submit(screen.getByRole('button', { name: /create/i }));
      await waitFor(() => expect(handleCreateChallenge).toHaveBeenCalled());
      expect(handleCreateChallenge.mock.calls[0][1]).toBeUndefined();
    });

    it('shows a refused value under its field', async () => {
      const handleCreateChallenge = vi.fn(async (e) => {
        e.preventDefault();
        return {
          code: 'ERR_INVALID_WORKSPACE_SIZE',
          error: 'Storage per student must be between 10 and 98 GiB.',
          field: 'workspace.workspace_gib',
          min: 10,
          max: 98,
        };
      });
      render(<ChallengeConfig {...defaultProps} handleCreateChallenge={handleCreateChallenge} />);
      fireEvent.submit(screen.getByRole('button', { name: /create/i }));
      await waitFor(() =>
        expect(screen.getByTestId('workspace-settings')).toHaveAttribute(
          'data-errors',
          JSON.stringify({ workspace_gib: 'Storage per student must be between 10 and 98 GiB.' }),
        ),
      );
    });
  });
});
