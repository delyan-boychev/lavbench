import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import PersonFields from '../PersonFields';

const challenges = [
  { id: 1, title: 'Spring Cup' },
  { id: 2, title: 'Autumn Cup' },
];

const value = {
  name: 'Ivan',
  middle_name: 'Petrov',
  surname: 'Ivanov',
  birth_date: '2010-01-02',
  grade: '9',
  school: 'PMG',
  city: 'Sofia',
  challenge_id: '1',
  is_anonymous: false,
};

function renderFields(props = {}) {
  const onChange = vi.fn();
  render(
    <PersonFields
      value={value}
      onChange={onChange}
      idPrefix="edit"
      challenges={challenges}
      {...props}
    />,
  );
  return onChange;
}

describe('PersonFields', () => {
  it('shows every competitor field with its value', () => {
    renderFields();
    expect(screen.getByLabelText(/^First Name/)).toHaveValue('Ivan');
    expect(screen.getByLabelText(/^Middle Name/)).toHaveValue('Petrov');
    expect(screen.getByLabelText(/^Last Name/)).toHaveValue('Ivanov');
    expect(screen.getByLabelText(/^Birth Date/)).toHaveValue('2010-01-02');
    expect(screen.getByLabelText(/^Grade/)).toHaveValue('9');
    expect(screen.getByLabelText(/^School/)).toHaveValue('PMG');
    expect(screen.getByLabelText(/^City/)).toHaveValue('Sofia');
    expect(screen.getByRole('combobox', { name: /Assign Competition/ })).toHaveTextContent(
      'Spring Cup',
    );
    expect(screen.getByLabelText(/^Anonymous/)).not.toBeChecked();
  });

  it('shows only the name fields for a non-competitor', () => {
    renderFields({ competitor: false });
    expect(screen.getByLabelText(/^First Name/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Last Name/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Middle Name/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Birth Date/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^School/)).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Anonymous/)).not.toBeInTheDocument();
  });

  it('patches only the edited field', () => {
    const onChange = renderFields();
    fireEvent.change(screen.getByLabelText(/^School/), { target: { value: 'SMG' } });
    expect(onChange).toHaveBeenLastCalledWith({ school: 'SMG' });

    fireEvent.click(screen.getByLabelText(/^Anonymous/));
    expect(onChange).toHaveBeenLastCalledWith({ is_anonymous: true });
  });

  it('patches the competition with the chosen id as a string', () => {
    const onChange = renderFields();
    fireEvent.click(screen.getByRole('combobox', { name: /Assign Competition/ }));
    fireEvent.click(screen.getByRole('option', { name: 'Autumn Cup' }));
    expect(onChange).toHaveBeenLastCalledWith({ challenge_id: '2' });
  });

  it('gives the anonymity toggle an id from idPrefix', () => {
    renderFields({ idPrefix: 'register' });
    expect(screen.getByLabelText(/^Anonymous/)).toHaveAttribute('id', 'register-is-anonymous');
  });

  it('shows field errors under their fields', () => {
    renderFields({
      value: { ...value, challenge_id: '' },
      errors: { surname: 'Surname is required', challenge_id: 'Pick a competition' },
    });
    expect(screen.getByText('Surname is required')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Last Name/)).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Pick a competition')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Assign Competition/ })).toHaveAttribute(
      'aria-invalid',
      'true',
    );
  });

  it('shows empty inputs for missing values', () => {
    renderFields({ value: { challenge_id: '' } });
    expect(screen.getByLabelText(/^First Name/)).toHaveValue('');
    expect(screen.getByRole('combobox', { name: /Assign Competition/ })).toHaveTextContent(
      '-- Choose Competition --',
    );
  });
});
