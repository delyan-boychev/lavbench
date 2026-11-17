import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import WorkspaceImagePicker from '../WorkspaceImagePicker';

const IMAGES = [
  {
    image_id: 'python-ml',
    name: 'Python ML (CPU)',
    description: 'pandas and scikit-learn',
    packages: [
      { name: 'pandas', version: '2.2.3' },
      { name: 'pyarrow', version: '18.1.0' },
    ],
    default: true,
  },
  { image_id: 'python-base', name: 'Python', packages: [], default: false },
];

describe('WorkspaceImagePicker', () => {
  it('lists the catalog and the installed libraries of the chosen image', () => {
    render(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value="python-ml"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getAllByText('Python ML (CPU)').length).toBeGreaterThan(0);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('pandas and scikit-learn');
    expect(tooltip).toHaveTextContent('pyarrow 18.1.0');
  });

  it('says when an image lists no libraries', () => {
    render(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value="python-base"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'nanoColab lists no libraries for this image.',
    );
  });

  it('keeps a stored image that nanoColab no longer offers', () => {
    render(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value="old-image"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getAllByText('old-image (no longer offered)').length).toBeGreaterThan(0);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('reports a catalog that could not be loaded', () => {
    render(
      <WorkspaceImagePicker images={undefined} loadFailed value="python-ml" onChange={vi.fn()} />,
    );
    expect(screen.getByText('Could not load the image list from nanoColab.')).toBeInTheDocument();
  });

  it('shows a server error under the select', () => {
    render(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value="python-ml"
        onChange={vi.fn()}
        error="Choose a workspace image from the list."
      />,
    );
    expect(screen.getByText('Choose a workspace image from the list.')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-invalid', 'true');
  });

  it('passes the picked image on', () => {
    const onChange = vi.fn();
    render(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value="python-ml"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(screen.getByRole('option', { name: /^Python$/ }));
    expect(onChange).toHaveBeenCalledWith('python-base');
  });
});
