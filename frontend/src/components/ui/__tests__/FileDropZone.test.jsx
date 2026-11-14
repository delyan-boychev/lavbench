import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FileDropZone from '../FileDropZone';

const notebook = () => new File(['{}'], 'solution.ipynb', { type: 'application/json' });
const fileDrag = (files = []) => ({ dataTransfer: { types: ['Files'], files } });

function renderZone(props = {}) {
  const onFiles = vi.fn();
  render(
    <FileDropZone onFiles={onFiles} className="zone" {...props}>
      <span>Drop here</span>
    </FileDropZone>,
  );
  const zone = screen.getByText('Drop here').closest('label');
  const input = zone.querySelector('input[type="file"]');
  return { onFiles, zone, input };
}

describe('FileDropZone', () => {
  it('clears the input after a pick so the same file can be chosen again', () => {
    const { onFiles, input } = renderZone();
    const file = notebook();
    // A browser fires no change event when the picked file equals the input's current value
    const setValue = vi.spyOn(input, 'value', 'set');

    fireEvent.change(input, { target: { files: [file] } });
    expect(onFiles).toHaveBeenCalledWith([file]);
    expect(setValue).toHaveBeenCalledWith('');

    fireEvent.change(input, { target: { files: [file] } });
    expect(onFiles).toHaveBeenCalledTimes(2);
  });

  it('passes a dropped file to onFiles and prevents the browser from opening it', () => {
    const { onFiles, zone } = renderZone();
    const file = notebook();

    const notCancelled = fireEvent.drop(zone, fileDrag([file]));

    expect(notCancelled).toBe(false);
    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it('keeps only the first dropped file unless multiple is set', () => {
    const first = notebook();
    const second = new File(['{}'], 'other.ipynb');

    const single = renderZone();
    fireEvent.drop(single.zone, fileDrag([first, second]));
    expect(single.onFiles).toHaveBeenCalledWith([first]);
  });

  it('passes every dropped file when multiple is set', () => {
    const first = notebook();
    const second = new File(['{}'], 'other.ipynb');
    const { onFiles, zone } = renderZone({ multiple: true });

    fireEvent.drop(zone, fileDrag([first, second]));

    expect(onFiles).toHaveBeenCalledWith([first, second]);
  });

  it('shows the drag-over state while a file is held over the zone', () => {
    const { zone } = renderZone({ draggingClassName: 'over' });

    expect(fireEvent.dragEnter(zone, fileDrag())).toBe(false);
    expect(zone).toHaveClass('zone', 'over');
    expect(fireEvent.dragOver(zone, fileDrag())).toBe(false);

    fireEvent.dragLeave(zone, fileDrag());
    expect(zone).not.toHaveClass('over');
  });

  it('ignores drags that carry no files', () => {
    const { zone } = renderZone({ draggingClassName: 'over' });

    expect(fireEvent.dragOver(zone, { dataTransfer: { types: ['text/plain'] } })).toBe(true);
    fireEvent.dragEnter(zone, { dataTransfer: { types: ['text/plain'] } });
    expect(zone).not.toHaveClass('over');
  });

  it('stops a file dropped next to the zone from navigating away', () => {
    renderZone();

    expect(fireEvent.drop(document.body, fileDrag([notebook()]))).toBe(false);
    expect(fireEvent.dragOver(document.body, fileDrag())).toBe(false);
  });
});
