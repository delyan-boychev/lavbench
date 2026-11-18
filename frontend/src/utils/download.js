/**
 * Trigger a browser download for a Blob and release its object URL afterwards.
 * @param {Blob} blob
 * @param {string} filename
 */
export function saveBlob(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Revoking synchronously can cancel the download in some browsers
  setTimeout(() => window.URL.revokeObjectURL?.(url), 0);
}

/**
 * The file name the server chose in Content-Disposition, or the fallback.
 * @param {Response} res
 * @param {string} fallback
 */
export function downloadName(res, fallback) {
  const header = res.headers?.get?.('Content-Disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match ? match[1] : fallback;
}
