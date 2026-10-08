import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Modal from '../Modal';
import SelectField from '../SelectField';

describe('Modal Component', () => {
  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <Modal isOpen={false} onClose={() => {}} title="Modal Title">
        <div>Modal Content</div>
      </Modal>,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders title, content and close button when isOpen is true', () => {
    render(
      <Modal isOpen={true} onClose={() => {}} title="Modal Title">
        <div>Modal Content</div>
      </Modal>,
    );
    expect(screen.getByText('Modal Title')).toBeInTheDocument();
    expect(screen.getByText('Modal Content')).toBeInTheDocument();
    expect(screen.getByTitle('Close')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });

  it('renders footer when provided', () => {
    render(
      <Modal isOpen={true} onClose={() => {}} title="Title" footer={<button>Save Changes</button>}>
        <div>Body</div>
      </Modal>,
    );
    expect(screen.getByText('Save Changes')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={handleClose} title="Title">
        <div>Body</div>
      </Modal>,
    );
    fireEvent.click(screen.getByTitle('Close'));
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when background overlay is clicked', () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={handleClose} title="Title">
        <div>Body</div>
      </Modal>,
    );

    // The overlay is the outermost div in the Portal
    const overlay = document.body.querySelector('.fixed');
    fireEvent.click(overlay);
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('does not call onClose when modal content itself is clicked', () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={handleClose} title="Title">
        <div>Body Content</div>
      </Modal>,
    );

    fireEvent.click(screen.getByText('Body Content'));
    expect(handleClose).not.toHaveBeenCalled();
  });

  it('calls onClose when Escape key is pressed', () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={handleClose} title="Title">
        <div>Body</div>
      </Modal>,
    );

    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('manages document body overflow style', () => {
    const { rerender, unmount } = render(
      <Modal isOpen={true} onClose={() => {}} title="Title">
        <div>Body</div>
      </Modal>,
    );
    expect(document.body.style.overflow).toBe('hidden');

    rerender(
      <Modal isOpen={false} onClose={() => {}} title="Title">
        <div>Body</div>
      </Modal>,
    );
    expect(document.body.style.overflow).toBe('');

    unmount();
    expect(document.body.style.overflow).toBe('');
  });

  it('closes only the topmost modal on Escape', () => {
    const closeOuter = vi.fn();
    const closeInner = vi.fn();
    const { rerender } = render(
      <Modal isOpen={true} onClose={closeOuter} title="Outer">
        <div>Outer body</div>
      </Modal>,
    );
    rerender(
      <>
        <Modal isOpen={true} onClose={closeOuter} title="Outer">
          <div>Outer body</div>
        </Modal>
        <Modal isOpen={true} onClose={closeInner} title="Inner">
          <div>Inner body</div>
        </Modal>
      </>,
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closeInner).toHaveBeenCalledTimes(1);
    expect(closeOuter).not.toHaveBeenCalled();

    rerender(
      <>
        <Modal isOpen={true} onClose={closeOuter} title="Outer">
          <div>Outer body</div>
        </Modal>
        <Modal isOpen={false} onClose={closeInner} title="Inner">
          <div>Inner body</div>
        </Modal>
      </>,
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closeOuter).toHaveBeenCalledTimes(1);
    expect(closeInner).toHaveBeenCalledTimes(1);
  });

  it('does not close when an open dropdown inside it consumes Escape', () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={handleClose} title="Title">
        <SelectField
          label="Pick"
          value=""
          onChange={() => {}}
          options={[
            { value: 'a', label: 'Alpha' },
            { value: 'b', label: 'Beta' },
          ]}
        />
      </Modal>,
    );

    const trigger = screen.getByRole('combobox');
    fireEvent.click(trigger);
    expect(screen.getByRole('listbox')).toBeInTheDocument();

    fireEvent.keyDown(trigger, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(handleClose).not.toHaveBeenCalled();

    fireEvent.keyDown(trigger, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });
});
