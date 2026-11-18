import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import HfDataSection from '../HfDataSection';

const SHA = '0123456789abcdef'.repeat(4);
const stored = {
  id: 't1',
  hf_folders: ['models/demo-org/tiny-model', 'datasets/demo-org/tiny-data'],
  hf_unpacked_bytes: 3 * 1024 * 1024,
  hf_file_count: 4,
  hf_zip_sha256: SHA,
  hf_skipped_count: 2,
  hf_zip_not_imported: false,
};
const zip = new File(['PK'], 'hf-data.zip', { type: 'application/zip' });

describe('HfDataSection', () => {
  it('offers a ZIP picker and the build hint when the task has no data', async () => {
    const user = userEvent.setup();
    const onFileChange = vi.fn();
    render(<HfDataSection onFileChange={onFileChange} />);

    expect(screen.getByText('No Hugging Face data yet.')).toBeInTheDocument();
    expect(screen.getByText('How to build the ZIP')).toBeInTheDocument();
    const command = screen.getByText('hf download <org>/<name> --local-dir models/<org>/<name>');
    // A phone scrolls the command sideways instead of breaking it mid-token
    expect(command).toHaveClass('whitespace-pre', 'overflow-x-auto');
    expect(command).not.toHaveClass('break-all');
    expect(screen.getByText('zip -r hf-data.zip models datasets')).toBeInTheDocument();

    const input = screen.getByTestId('hf-data').querySelector('input[type="file"]');
    expect(input).toHaveAttribute('accept', '.zip');
    await user.upload(input, zip);
    expect(onFileChange).toHaveBeenCalledWith(zip);
  });

  it('shows the stored folders, sizes, skipped hidden files and a short hash', () => {
    render(<HfDataSection task={stored} />);
    const current = screen.getByTestId('hf-current');
    expect(current).toHaveTextContent('models/demo-org/tiny-model/');
    expect(current).toHaveTextContent('datasets/demo-org/tiny-data/');
    expect(current).toHaveTextContent('3 MB');
    expect(current).toHaveTextContent('4 files');
    expect(current).toHaveTextContent('2 hidden files skipped');
    expect(screen.getByText(`SHA-256 ${SHA.slice(0, 12)}`)).toHaveAttribute('title', SHA);
    expect(screen.getByText('Replace with another ZIP')).toBeInTheDocument();
  });

  it('marks the stored data for removal on Save and offers to undo the mark', async () => {
    const user = userEvent.setup();
    const onToggleRemove = vi.fn();
    const { rerender } = render(<HfDataSection task={stored} onToggleRemove={onToggleRemove} />);
    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(onToggleRemove).toHaveBeenCalledTimes(1);

    rerender(<HfDataSection task={stored} removeMarked onToggleRemove={onToggleRemove} />);
    expect(screen.getByTestId('hf-current')).toHaveTextContent(
      'Removed when you save. Notebooks that read these folders fail until you upload a ZIP again.',
    );
    expect(screen.getByText('models/demo-org/tiny-model/')).toHaveClass('line-through');
    await user.click(screen.getByRole('button', { name: 'Undo Delete' }));
    expect(onToggleRemove).toHaveBeenCalledTimes(2);
  });

  it('drops the removal mark while a picked ZIP is to replace the data', () => {
    render(<HfDataSection task={stored} file={zip} removeMarked />);
    expect(screen.queryByText(/Removed when you save/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo Delete' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
  });

  it('shows the picked file with its size and lets it be cleared', async () => {
    const user = userEvent.setup();
    const onFileChange = vi.fn();
    render(<HfDataSection task={stored} file={zip} onFileChange={onFileChange} />);
    expect(screen.getByTestId('hf-picked')).toHaveTextContent('hf-data.zip');
    expect(
      screen.getByText('The ZIP uploads after you save and then replaces the current data.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /hf-data\.zip/ }));
    expect(onFileChange).toHaveBeenCalledWith(null);
  });

  it('hides Remove while uploads run', () => {
    render(<HfDataSection task={stored} busy />);
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
  });

  it('keeps published data fixed with the lock notice', () => {
    render(<HfDataSection task={stored} locked />);
    expect(
      screen.getByText('The workspaces are published, so these files are fixed.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
    expect(screen.getByTestId('hf-data').querySelector('input[type="file"]')).toBeNull();
    expect(screen.getByTestId('hf-current')).toHaveTextContent('models/demo-org/tiny-model/');
  });

  it('asks for the ZIP again after an import', () => {
    render(<HfDataSection task={{ ...stored, hf_zip_not_imported: true }} />);
    expect(
      screen.getByText(
        'The Hugging Face data was not included in the import. Upload the ZIP again.',
      ),
    ).toBeInTheDocument();
  });

  it('says one file and one skipped entry in the singular', () => {
    render(<HfDataSection task={{ ...stored, hf_file_count: 1, hf_skipped_count: 1 }} />);
    expect(screen.getByTestId('hf-current')).toHaveTextContent('1 file · 1 hidden file skipped');
  });
});
