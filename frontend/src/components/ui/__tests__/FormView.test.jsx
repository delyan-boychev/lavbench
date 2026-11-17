import React, { useState } from 'react';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import FormView from '../FormView';
import InputField from '../InputField';
import SelectField from '../SelectField';
import { renderWithProviders } from '../../../test-utils';

function Editor({ onSubmit = vi.fn(), onCancel = vi.fn(), dirty = false, errors = null, ...rest }) {
  return (
    <FormView
      title="Edit thing"
      submitLabel="Save"
      onSubmit={onSubmit}
      onCancel={onCancel}
      dirty={dirty}
      errors={errors}
      {...rest}
    >
      <InputField label="Username" value="admin" onChange={() => {}} disabled />
      <InputField label="Title" value="" onChange={() => {}} />
      <SelectField label="Competition" value="" onChange={() => {}} options={[]} required />
    </FormView>
  );
}

describe('FormView', () => {
  it('shows the title, Back, Cancel and Save and submits the form', async () => {
    const onSubmit = vi.fn();
    renderWithProviders(<Editor onSubmit={onSubmit} />);

    expect(screen.getByRole('heading', { name: 'Edit thing' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Back/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();

    fireEvent.submit(screen.getByRole('button', { name: 'Save' }).closest('form'));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('focuses the first enabled field on open', async () => {
    renderWithProviders(<Editor />);
    expect(screen.getByLabelText('Title')).toHaveFocus();
  });

  it('leaves out Back and Cancel for an always-open form', () => {
    renderWithProviders(<Editor showBack={false} onCancel={null} autoFocus={false} />);
    expect(screen.queryByRole('button', { name: /Back/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Title')).not.toHaveFocus();
  });

  it('cancels at once when nothing changed', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    renderWithProviders(<Editor onCancel={onCancel} />);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Discard unsaved changes?')).not.toBeInTheDocument();
  });

  it('asks before discarding unsaved changes', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    renderWithProviders(<Editor onCancel={onCancel} dirty />);

    await user.click(screen.getByRole('button', { name: /Back/ }));
    expect(await screen.findByText('Discard unsaved changes?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(onCancel).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(await screen.findByRole('button', { name: 'Discard changes' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('asks the browser to confirm leaving the page while dirty', () => {
    const { rerender } = renderWithProviders(<Editor dirty />);
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);

    rerender(<Editor dirty={false} />);
    const clean = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
  });

  it('focuses the combobox when a required SelectField is invalid', async () => {
    renderWithProviders(<Editor />);
    const hiddenSelect = document.querySelector('select[aria-hidden="true"]');
    fireEvent.invalid(hiddenSelect);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
  });

  it('focuses the first field with a server error after a failed save', async () => {
    function ServerErrors() {
      const [errors, setErrors] = useState(null);
      return (
        <FormView
          title="Edit"
          submitLabel="Save"
          onSubmit={() => setErrors({ email: 'Invalid email' })}
          errors={errors}
        >
          <InputField label="Name" value="" onChange={() => {}} />
          <InputField label="Email" value="" onChange={() => {}} error={errors?.email} />
        </FormView>
      );
    }
    renderWithProviders(<ServerErrors />);
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }).closest('form'));
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveFocus());
    expect(screen.getByText('Invalid email')).toBeInTheDocument();
  });

  it('returns the focus to the button that opened it', async () => {
    const user = userEvent.setup();
    function Page() {
      const [open, setOpen] = useState(false);
      return open ? (
        <Editor onCancel={() => setOpen(false)} />
      ) : (
        <button type="button" data-return-id="edit-1" onClick={() => setOpen(true)}>
          Edit row
        </button>
      );
    }
    renderWithProviders(<Page />);
    await user.click(screen.getByRole('button', { name: 'Edit row' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit row' })).toHaveFocus());
  });
});
