import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SelectField from '../SelectField';

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
    expect(screen.getByRole('combobox', { name: /Select Option/i })).toBeInTheDocument();
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
    const btn = screen.getByRole('combobox', { name: /Choose/i });
    fireEvent.click(btn);

    // Click Option 2 in the dropdown menu (which has role button inside container)
    const option2Btn = screen.getByRole('option', { name: /^Option 2$/i });
    fireEvent.click(option2Btn);

    expect(handleChange).toHaveBeenCalledWith('option2');
  });

  it('respects the disabled state', () => {
    render(
      <SelectField label="Disabled Select" options={options} disabled={true} onChange={() => {}} />,
    );
    expect(screen.getByRole('combobox', { name: /Disabled Select/i })).toBeDisabled();
  });

  it('supports searching/filtering options', () => {
    render(
      <SelectField label="Search Select" options={options} searchable={true} onChange={() => {}} />,
    );

    // Open dropdown
    fireEvent.click(screen.getByRole('combobox', { name: /Search Select/i }));

    // Find search input
    const input = screen.getByPlaceholderText(/Search/i);
    expect(input).toBeInTheDocument();

    // Type query
    fireEvent.change(input, { target: { value: 'Option 2' } });

    // Option 1 should be filtered out, Option 2 should be present in custom buttons
    expect(screen.queryByRole('option', { name: /^Option 1$/i })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: /^Option 2$/i })).toBeInTheDocument();
  });

  it('supports multiple selections', () => {
    const handleChange = vi.fn();
    render(
      <SelectField
        label="Multi Select"
        options={options}
        multiple={true}
        value={['option1']}
        onChange={handleChange}
      />,
    );

    // Button should display selected options summary
    expect(screen.getByRole('combobox', { name: /Multi Select/i })).toBeInTheDocument();

    // Open dropdown
    fireEvent.click(screen.getByRole('combobox', { name: /Multi Select/i }));

    // Click Option 2 to add to selection
    fireEvent.click(screen.getByRole('option', { name: /^Option 2$/i }));
    expect(handleChange).toHaveBeenCalledWith(['option1', 'option2']);
  });

  it('supports keyboard navigation and selection', () => {
    const handleChange = vi.fn();
    render(<SelectField label="Keyboard" options={options} onChange={handleChange} />);

    const combobox = screen.getByRole('combobox', { name: 'Keyboard' });
    fireEvent.keyDown(combobox, { key: 'ArrowDown' });
    fireEvent.keyDown(combobox, { key: 'ArrowDown' });
    fireEvent.keyDown(combobox, { key: 'Enter' });

    expect(handleChange).toHaveBeenCalledWith('option2');
  });
});
