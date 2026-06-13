import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import InputField from './InputField';

describe('InputField Component', () => {
  it('renders input with label and placeholder', () => {
    render(
      <InputField
        label="Username"
        placeholder="Enter username"
        value=""
        onChange={() => {}}
      />
    );
    expect(screen.getByLabelText('Username')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Enter username')).toBeInTheDocument();
  });

  it('renders asterisk when required is true', () => {
    render(<InputField label="Email" required={true} value="" onChange={() => {}} />);
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('displays hint text when provided', () => {
    render(<InputField label="Password" hint="Must be at least 8 characters" value="" onChange={() => {}} />);
    expect(screen.getByText('Must be at least 8 characters')).toBeInTheDocument();
  });

  it('triggers onChange handler when value changes', () => {
    const handleChange = vi.fn();
    render(<InputField label="Name" value="" onChange={handleChange} />);
    
    const input = screen.getByLabelText('Name');
    fireEvent.change(input, { target: { value: 'John' } });
    
    expect(handleChange).toHaveBeenCalledTimes(1);
  });

  it('respects the disabled state', () => {
    render(<InputField label="Disabled Input" disabled={true} value="" onChange={() => {}} />);
    expect(screen.getByLabelText('Disabled Input')).toBeDisabled();
  });

  it('uses custom id when provided', () => {
    render(<InputField label="Custom ID Input" id="my-unique-id" value="" onChange={() => {}} />);
    const input = screen.getByLabelText('Custom ID Input');
    expect(input).toHaveAttribute('id', 'my-unique-id');
  });

  it('generates fallback id from label when no id is provided', () => {
    render(<InputField label="Fallback ID Input" value="" onChange={() => {}} />);
    const input = screen.getByLabelText('Fallback ID Input');
    expect(input).toHaveAttribute('id', 'fallback-id-input');
  });
});
