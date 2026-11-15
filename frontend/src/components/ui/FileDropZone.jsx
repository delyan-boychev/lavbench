import React, { useEffect, useRef, useState } from 'react';

const carriesFiles = (e) => Array.from(e.dataTransfer?.types || []).includes('Files');

/**
 * A file picker that also accepts dropped files. The input is cleared after every pick,
 * so choosing the same file again calls onFiles again.
 */
export default function FileDropZone({
  onFiles,
  accept = undefined,
  multiple = false,
  className = '',
  draggingClassName = 'is-dragging',
  children = null,
}) {
  const [isDragging, setIsDragging] = useState(false);
  // dragenter and dragleave also fire for child elements, so count the nesting depth
  const depth = useRef(0);

  // A file dropped next to the zone would make the browser open it and leave the page
  useEffect(() => {
    const blockFileDrop = (e) => {
      if (carriesFiles(e)) e.preventDefault();
    };
    window.addEventListener('dragover', blockFileDrop);
    window.addEventListener('drop', blockFileDrop);
    return () => {
      window.removeEventListener('dragover', blockFileDrop);
      window.removeEventListener('drop', blockFileDrop);
    };
  }, []);

  const deliver = (fileList) => {
    const files = Array.from(fileList || []);
    if (files.length > 0) onFiles(multiple ? files : files.slice(0, 1));
  };

  const handleChange = (e) => {
    deliver(e.target.files);
    e.target.value = '';
  };

  const handleDragEnter = (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    depth.current += 1;
    setIsDragging(true);
  };

  const handleDragOver = (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (e) => {
    if (!carriesFiles(e)) return;
    depth.current = Math.max(0, depth.current - 1);
    if (depth.current === 0) setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    depth.current = 0;
    setIsDragging(false);
    deliver(e.dataTransfer?.files);
  };

  return (
    <label
      className={isDragging ? `${className} ${draggingClassName}` : className}
      data-dragging={isDragging || undefined}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <input
        type="file"
        className="sr-only"
        accept={accept}
        multiple={multiple}
        onChange={handleChange}
      />
      {children}
    </label>
  );
}
