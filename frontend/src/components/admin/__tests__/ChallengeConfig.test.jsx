import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../ui/InputField', () => ({
  default: ({ label, value, onChange, type, multiline, rows, required }) => (
    <div>
      {label && <label>{label}</label>}
      {multiline ? (
        <textarea data-testid="textarea" value={value} onChange={onChange} rows={rows} required={required} />
      ) : (
        <input type={type || 'text'} value={value} onChange={onChange} required={required} />
      )}
    </div>
  ),
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, type, variant, className, disabled }) => (
    <button type={type} data-variant={variant} className={className} disabled={disabled}>{children}</button>
  ),
}));

vi.mock('../../ui/SelectField', () => ({
  default: ({ label, value, onChange, options, required }) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} required={required}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
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

import ChallengeConfig from '../ChallengeConfig';

const defaultProps = {
  handleCreateChallenge: vi.fn(e => e.preventDefault()),
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
  timezones: [
    { value: 'UTC', label: 'UTC' },
    { value: 'Europe/Sofia', label: 'Europe/Sofia' },
  ],
};

describe('ChallengeConfig', () => {
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
    const handleCreateChallenge = vi.fn(e => e.preventDefault());
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
    render(<ChallengeConfig {...defaultProps} newChallenge={{ ...defaultProps.newChallenge, gpu_required: false }} />);
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
    expect(screen.getByRole('button', { name: /create/i })).toBeInTheDocument();
  });
});
