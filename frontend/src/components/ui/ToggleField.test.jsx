import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ToggleField from './ToggleField';

describe('ToggleField Component', () => {
  it('renders check box with label', () => {
    render(
      <ToggleField label="Test Toggle" id="test-toggle" checked={false} onChange={() => {}} />,
    );
    expect(screen.getByText('Test Toggle')).toBeInTheDocument();
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
  });

  it('triggers onChange handler when clicked', () => {
    const handleChange = vi.fn();
    render(
      <ToggleField label="Click Me" id="click-toggle" checked={false} onChange={handleChange} />,
    );
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);
    expect(handleChange).toHaveBeenCalled();
  });

  it('respects the disabled state', () => {
    render(
      <ToggleField
        label="Disabled Toggle"
        id="disabled-toggle"
        checked={true}
        disabled={true}
        onChange={() => {}}
      />,
    );
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).toBeDisabled();
    expect(checkbox).toBeChecked();
  });
});
