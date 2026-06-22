import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FileUploader from '../FileUploader';

function createFile(name, _size = 1024, type = 'text/plain') {
  return new File(['test'], name, { type });
}

describe('FileUploader Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders label, description, and required badge', () => {
    render(<FileUploader label="Upload Files" description="Select your files" required />);

    expect(screen.getByText('Upload Files')).toBeInTheDocument();
    expect(screen.getByText('Select your files')).toBeInTheDocument();
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('accepts file selection via input change', () => {
    const handleChange = vi.fn();
    const files = [createFile('test.txt')];
    render(<FileUploader onChange={handleChange} />);

    const fileInput = document.querySelector('input[type="file"]');
    fireEvent.change(fileInput, { target: { files } });

    expect(handleChange).toHaveBeenCalled();
  });

  it('displays selected file names', () => {
    const files = [createFile('document.pdf'), createFile('image.png')];
    render(<FileUploader files={files} />);

    expect(screen.getByText('document.pdf')).toBeInTheDocument();
    expect(screen.getByText('image.png')).toBeInTheDocument();
  });

  it('calls onChange when files change', () => {
    const handleChange = vi.fn();
    const files = [createFile('test.txt')];
    render(<FileUploader onChange={handleChange} />);

    const fileInput = document.querySelector('input[type="file"]');
    fireEvent.change(fileInput, { target: { files } });

    expect(handleChange).toHaveBeenCalled();
  });

  it('respects maxFiles limit', () => {
    const files = [createFile('file1.txt'), createFile('file2.txt'), createFile('file3.txt')];
    const handleChange = vi.fn();
    render(<FileUploader onChange={handleChange} maxFiles={2} multiple />);

    const fileInput = document.querySelector('input[type="file"]');
    fireEvent.change(fileInput, { target: { files } });

    expect(handleChange).toHaveBeenCalled();
    const result = handleChange.mock.calls[0][0];
    const merged = result([]);
    expect(merged.length).toBeLessThanOrEqual(2);
  });

  it('shows existing files with delete button', () => {
    const existingFiles = [
      { filename: 'existing1.txt', size_bytes: 2048 },
      { filename: 'existing2.txt', size_bytes: 4096 },
    ];

    render(<FileUploader existingFiles={existingFiles} />);

    expect(screen.getByText('existing1.txt')).toBeInTheDocument();
    expect(screen.getByText('existing2.txt')).toBeInTheDocument();
    const deleteButtons = screen.getAllByText('Delete');
    expect(deleteButtons).toHaveLength(2);
  });

  it('removes existing file on delete button click', () => {
    const handleRemoveExisting = vi.fn();
    const existingFiles = [{ filename: 'existing1.txt', size_bytes: 2048 }];

    render(<FileUploader existingFiles={existingFiles} onRemoveExisting={handleRemoveExisting} />);

    fireEvent.click(screen.getByText('Delete'));

    expect(handleRemoveExisting).toHaveBeenCalledWith('existing1.txt');
  });

  it('validates required files', () => {
    render(<FileUploader required />);

    const hiddenInput = document.querySelector('input[type="text"][required]');
    expect(hiddenInput).toBeInTheDocument();
    expect(hiddenInput).toHaveAttribute('aria-hidden', 'true');
  });
});
