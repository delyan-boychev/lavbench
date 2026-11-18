// The server always hides these two, whichever zone they were dropped in
export const LABELS_FILE = 'labels.parquet';
export const BASELINE_SUBMISSION_FILE = 'baseline_submission.parquet';
const ALWAYS_HIDDEN = new Set([LABELS_FILE, BASELINE_SUBMISSION_FILE]);

/** A task's `files`, which older responses sent as a JSON string. */
export function parseTaskFiles(files) {
  if (Array.isArray(files)) return files;
  if (typeof files === 'string' && files.trim() !== '') {
    try {
      const parsed = JSON.parse(files);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

/** `hidden` for a name the server always hides, otherwise the zone it was dropped in. */
export function uploadVisibility(name, zone) {
  return ALWAYS_HIDDEN.has(name) ? 'hidden' : zone;
}

/** The visibility the API reports for a stored file. */
export function storedVisibility(entry) {
  return entry.visibility || uploadVisibility(entry.filename, 'public');
}
