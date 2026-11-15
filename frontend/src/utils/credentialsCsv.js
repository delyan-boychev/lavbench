import { saveBlob } from './download';

const HEADERS = ['ID', 'Name', 'Middle Name', 'Surname', 'Birth Date', 'Username', 'Password'];

// A cell whose first visible character is = + @ or - would run as a spreadsheet formula,
// so prefix it with a quote; leading control characters and spaces do not hide it
function csvCell(value) {
  const text = String(value ?? '');
  let first = 0;
  while (first < text.length && text.charCodeAt(first) <= 32) first += 1;
  const lead = text.slice(first)[0];
  const safe = lead && '=+@-'.includes(lead) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}

function slugify(title) {
  if (!title) return 'competition';
  return title
    .toLowerCase()
    .replace(/[^a-z0-9а-яё\s-_]+/gi, '')
    .trim()
    .replace(/\s+/g, '_');
}

/**
 * Build the competitor credentials CSV (UTF-8 with BOM so spreadsheets read Cyrillic).
 * @param {Array<{id?: string, name?: string|null, middle_name?: string|null, surname?: string|null, birth_date?: string|null, username?: string, password?: string}>} rows
 * @returns {Blob}
 */
export function buildCredentialsCsv(rows) {
  const lines = [
    HEADERS.join(','),
    ...rows.map((r) =>
      [r.id, r.name, r.middle_name, r.surname, r.birth_date, r.username, r.password]
        .map(csvCell)
        .join(','),
    ),
  ];
  return new Blob([new Uint8Array([0xef, 0xbb, 0xbf]), lines.join('\n')], {
    type: 'text/csv;charset=utf-8;',
  });
}

/**
 * Save competitor credentials as a CSV file named after the competition and the time.
 * @param {Parameters<typeof buildCredentialsCsv>[0]} rows
 * @param {string | undefined} challengeTitle
 */
export function downloadCredentialsCsv(rows, challengeTitle) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}`;
  saveBlob(
    buildCredentialsCsv(rows),
    `${slugify(challengeTitle)}_competitors_credentials_${stamp}.csv`,
  );
}
