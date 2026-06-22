import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SelectField from './SelectField';

describe('SelectField Component', () => {
  const options = [
    { value: 'option1', label: 'Option 1' },
    { value: 'option2', label: 'Option 2' },
  ];

  it('renders select with label and options', () => {
    render(
      <SelectField label="Select Option" options={options} value="option1" onChange={() => {}} />,
    );
    expect(screen.getByText('Select Option')).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeInTheDocument();
    expect(screen.getByText('Option 1')).toBeInTheDocument();
  });

  it('renders asterisk when required is true', () => {
    render(<SelectField label="Choose" options={options} required={true} onChange={() => {}} />);
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('triggers onChange handler when option is selected', () => {
    const handleChange = vi.fn();
    render(
      <SelectField label="Choose" options={options} value="option1" onChange={handleChange} />,
    );

    // Click button to open dropdown
    const btn = screen.getByRole('button');
    fireEvent.click(btn);

    // Click Option 2 in the dropdown menu
    const option2Btn = screen.getByText('Option 2');
    fireEvent.click(option2Btn);

    expect(handleChange).toHaveBeenCalledWith('option2');
  });

  it('respects the disabled state', () => {
    render(
      <SelectField label="Disabled Select" options={options} disabled={true} onChange={() => {}} />,
    );
    expect(screen.getByRole('button')).toBeDisabled();
  });
});
