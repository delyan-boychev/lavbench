import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompetitionFields from '../CompetitionFields';

const value = {
  title: 'Spring Cup',
  description: 'Machine learning',
  max_eval_requests: 5,
  ram_limit_mb: null,
  time_limit_sec: 600,
  start_time: '2026-05-01T09:00:00Z',
  end_time: '2026-05-03T18:00:00Z',
  timezone: 'Europe/Sofia',
  gpu_required: false,
  is_frozen: false,
};

const testStage = { start_time: '2026-04-28T10:00:00Z', end_time: '2026-04-29T12:30:00Z' };

function renderFields(props = {}) {
  const onChange = vi.fn();
  const view = render(
    <CompetitionFields value={value} onChange={onChange} idPrefix="edit" {...props} />,
  );
  return { onChange, ...view };
}

describe('CompetitionFields', () => {
  it('shows the values, with API times as local datetime values', () => {
    renderFields();
    expect(screen.getByLabelText(/^Competition Title/)).toHaveValue('Spring Cup');
    expect(screen.getByLabelText(/^Description/)).toHaveValue('Machine learning');
    expect(screen.getByLabelText(/^Daily Limits/)).toHaveValue(5);
    expect(screen.getByLabelText(/^Start Time/)).toHaveValue('2026-05-01T09:00');
  });

  it('shows the existing test stage times until they are edited', () => {
    const { rerender, onChange } = renderFields({ testStage });
    expect(screen.getByLabelText(/^Test Stage Start/)).toHaveValue('2026-04-28T10:00');
    expect(screen.getByLabelText(/^Test Stage End/)).toHaveValue('2026-04-29T12:30');

    rerender(
      <CompetitionFields
        value={{ ...value, test_stage_start_time: '2026-04-27T08:00', test_stage_end_time: '' }}
        onChange={onChange}
        idPrefix="edit"
        testStage={testStage}
      />,
    );
    expect(screen.getByLabelText(/^Test Stage Start/)).toHaveValue('2026-04-27T08:00');
    // A cleared time stays cleared rather than falling back to the stage
    expect(screen.getByLabelText(/^Test Stage End/)).toHaveValue('');
  });

  it('shows a refused test stage end under its field and clears it on edit', () => {
    const onFieldEdit = vi.fn();
    renderFields({
      errors: { test_stage_end_time: 'The test stage must end before the competition starts.' },
      onFieldEdit,
    });
    const end = screen.getByLabelText(/^Test Stage End/);
    expect(end).toHaveAttribute('aria-invalid', 'true');
    expect(
      screen.getByText('The test stage must end before the competition starts.'),
    ).toBeInTheDocument();
    fireEvent.change(end, { target: { value: '2026-04-30T08:00' } });
    expect(onFieldEdit).toHaveBeenCalledWith('test_stage_end_time');
  });

  it('leaves the test stage times empty without a test stage', () => {
    renderFields();
    expect(screen.getByLabelText(/^Test Stage Start/)).toHaveValue('');
    expect(screen.getByLabelText(/^Test Stage End/)).toHaveValue('');
  });

  it('gives the toggles ids from idPrefix', () => {
    const { container } = renderFields({ idPrefix: 'create' });
    expect(container.querySelector('#create-gpu-req')).toBeInTheDocument();
    expect(container.querySelector('#create-double-blind')).toBeInTheDocument();
    expect(container.querySelector('#create-is-frozen')).toBeInTheDocument();
  });

  it('defaults double-blind evaluation to on', () => {
    renderFields();
    expect(screen.getByLabelText('Double-Blind Evaluation')).toBeChecked();
    expect(screen.getByLabelText('Requires GPU Workers')).not.toBeChecked();
  });

  it('patches only the edited field', () => {
    const { onChange } = renderFields();
    fireEvent.change(screen.getByLabelText(/^Competition Title/), {
      target: { value: 'Autumn Cup' },
    });
    expect(onChange).toHaveBeenLastCalledWith({ title: 'Autumn Cup' });

    fireEvent.change(screen.getByLabelText(/^Daily Limits/), { target: { value: '12' } });
    expect(onChange).toHaveBeenLastCalledWith({ max_eval_requests: 12 });

    fireEvent.change(screen.getByLabelText(/^Test Stage Start/), {
      target: { value: '2026-04-20T10:00' },
    });
    expect(onChange).toHaveBeenLastCalledWith({ test_stage_start_time: '2026-04-20T10:00' });

    fireEvent.click(screen.getByLabelText('Freeze Leaderboard & Submissions'));
    expect(onChange).toHaveBeenLastCalledWith({ is_frozen: true });

    fireEvent.click(screen.getByLabelText('Double-Blind Evaluation'));
    expect(onChange).toHaveBeenLastCalledWith({ double_blind: false });
  });

  it('shows the chosen timezone and patches a new one', () => {
    const { onChange } = renderFields();
    const combobox = screen.getByRole('combobox', { name: /Competition Timezone/ });
    expect(combobox).toHaveTextContent('Europe/Sofia');
    fireEvent.click(combobox);
    fireEvent.change(screen.getByPlaceholderText('Search...'), { target: { value: 'Tokyo' } });
    fireEvent.click(screen.getByRole('option', { name: 'Asia/Tokyo' }));
    expect(onChange).toHaveBeenLastCalledWith({ timezone: 'Asia/Tokyo' });
  });
});
