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
      <SelectField
        label="Select Option"
        options={options}
        value="option1"
        onChange={() => {}}
      />
    );
    expect(screen.getByLabelText('Select Option')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue('option1');
    expect(screen.getByText('Option 1')).toBeInTheDocument();
    expect(screen.getByText('Option 2')).toBeInTheDocument();
  });

  it('renders asterisk when required is true', () => {
    render(<SelectField label="Choose" options={options} required={true} onChange={() => {}} />);
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('triggers onChange handler when option is selected', () => {
    const handleChange = vi.fn();
    render(<SelectField label="Choose" options={options} value="option1" onChange={handleChange} />);
    
    const select = screen.getByLabelText('Choose');
    fireEvent.change(select, { target: { value: 'option2' } });
    
    expect(handleChange).toHaveBeenCalledTimes(1);
  });

  it('respects the disabled state', () => {
    render(<SelectField label="Disabled Select" options={options} disabled={true} onChange={() => {}} />);
    expect(screen.getByLabelText('Disabled Select')).toBeDisabled();
  });
});
